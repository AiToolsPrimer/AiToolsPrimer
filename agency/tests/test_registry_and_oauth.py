import pytest

from agency.models import registry
from agency.platforms import oauth1


def test_every_task_has_commercial_license_and_fits_alone_in_64gb():
    for task in registry.ASSIGNMENTS:
        for m in registry.candidates(task):
            assert "non-commercial" not in m.license.lower(), m.name
        for profile in ("m5pro-64gb", "m5pro-64gb-b", "32gb"):
            m = registry.resolve(task, profile)
            assert m.memory_gb <= 56, (task, profile, m.name)   # one model at a time: what a 64 GB profile loads must fit alone


def test_profiles_and_overrides():
    assert registry.resolve("brain", "m5pro-64gb").name == "Qwen3.8-Flash-Next"
    assert registry.resolve("director", "m5pro-64gb").name == "Qwen3.8-Flash-Next"   # alias of brain
    assert registry.resolve("brain", "m5pro-64gb-b").name == "Qwen3.8-27B (8-bit)"
    assert registry.resolve("image", "32gb").name == "Z-Image-Turbo"
    assert registry.resolve("tts", overrides={"tts": "Kokoro 82M"}).name == "Kokoro 82M"
    with pytest.raises(KeyError):
        registry.resolve("tts", overrides={"tts": "ElevenLabs"})


def test_brain_candidates_are_ordered_strongest_first():
    names = [m.name for m in registry.candidates("brain")]
    assert names[0] == "Qwen3.8-Flash-Next" and "27B" in names[1]


def test_oauth1_matches_the_documented_x_example():
    # The worked example from X's "Creating a signature" developer page.
    header = oauth1.sign(
        "POST", "https://api.twitter.com/1.1/statuses/update.json?include_entities=true",
        {"status": "Hello Ladies + Gentlemen, a signed OAuth request!"},
        "xvz1evFS4wEEPTGEFPHBog", "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
        "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb", "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
        nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", timestamp="1318622958",
    )
    assert 'oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"' in header
