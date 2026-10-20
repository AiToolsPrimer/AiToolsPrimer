import pytest

from agency.models import registry
from agency.platforms import oauth1


def test_every_task_has_commercial_license_and_fits_64gb():
    for task in registry.ASSIGNMENTS:
        m = registry.resolve(task, "m5pro-64gb")
        assert "non-commercial" not in m.license.lower()
        assert m.memory_gb <= 36, task


def test_profiles_and_overrides():
    assert registry.resolve("vision", "m5pro-64gb").name == "Qwen3-VL-8B"
    assert registry.resolve("vision", "128gb").name == "Qwen3.8-27B"
    assert registry.resolve("image", "32gb").name == "Z-Image-Turbo"
    assert registry.resolve("tts", overrides={"tts": "Kokoro 82M"}).name == "Kokoro 82M"
    with pytest.raises(KeyError):
        registry.resolve("tts", overrides={"tts": "ElevenLabs"})


def test_director_plus_heaviest_media_fits_budget():
    plan = registry.memory_plan("m5pro-64gb")
    heaviest = max(v for k, v in plan.items() if k not in ("director", "writer", "coder"))
    assert plan["director"] + heaviest <= 44


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
