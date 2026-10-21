from agency.agents.factcheck import FactChecker, html_to_text, looks_english, number_check, split_sentences


def test_language_guard():
    assert looks_english("We tested five free PDF editors on a real contract and two of them added a watermark.")
    assert not looks_english("Abbiamo provato cinque editor PDF gratuiti su un contratto vero e due hanno aggiunto una filigrana.")
    assert looks_english("#pdf #tools")  # too short to judge


def test_number_guard_allows_facts_and_small_counts_only():
    facts = "[F1] 45% of users leave after the trial. [F2] Price is $12 per month."
    assert number_check("It keeps 45% of users.", facts) == []
    assert number_check("It costs $12 per month.", facts) == []
    assert number_check("It costs $15 per month.", facts) == ["$15"]
    assert number_check("Here are 5 tools we tried.", facts) == []          # small list count
    assert number_check("It is 3 times faster.", facts) == ["3"]
    assert number_check("Back in 2024 it was free.", facts) == []           # a year


def test_split_and_html():
    assert split_sentences("One. Two! Three? Four") == ["One.", "Two!", "Three?", "Four"]
    text = html_to_text("<html><script>x()</script><h1>Title</h1><p>Body &amp; more</p><footer>f</footer></html>")
    assert "Title" in text and "Body & more" in text and "x()" not in text and "f" not in text.split()[-1:]


def test_verify_removes_unsupported_and_keeps_supported(agency):
    fc: FactChecker = agency.factcheck
    facts = fc.facts_for("https://aitoolsprimer.com/pdf")
    assert len(facts) == 3 and agency.store.get_facts("https://aitoolsprimer.com/pdf")
    text = "We tested five free PDF editors on a real contract. This unsupported one cures headaches. It is 3 times faster. Want the table? The guide has it: https://aitoolsprimer.com/pdf"
    r = fc.verify(text, facts)
    assert r.ok
    assert "cures" not in r.text and "3 times" not in r.text
    assert "We tested five free PDF editors" in r.text and "Want the table?" in r.text
    reasons = [x["reason"] for x in r.removed]
    assert any("number" in x for x in reasons) and any("not in the guide" in x for x in reasons)
    assert r.supported >= 1 and "F1" in r.facts_used


def test_verify_without_facts_is_strict(agency):
    fc: FactChecker = agency.factcheck
    r = fc.verify("This tool is the fastest. Which one do you use?", [])
    assert r.text == "Which one do you use?"
    assert any("promise" in x["reason"] for x in r.removed)


def test_non_english_is_rejected(agency):
    r = agency.factcheck.verify("Abbiamo provato cinque editor PDF gratuiti su un contratto vero e due hanno aggiunto una filigrana.", [])
    assert not r.ok and not r.language_ok


def test_post_pipeline_records_factcheck_and_team(agency):
    cid = agency.director.produce_post("bluesky", "free PDF editors", "tested", link="https://aitoolsprimer.com/pdf")
    row = agency.store.get_content(cid)
    assert row["status"] == "queued"
    assert row["meta"]["factcheck"]["kept"] >= 1
    assert row["meta"]["facts"].startswith("[F1]")


def test_video_scenes_are_verified(agency):
    ids = agency.director.produce_video("free PDF editors", "tested", link="https://aitoolsprimer.com/pdf", target_seconds=60)
    video = next(agency.store.get_content(i) for i in ids if agency.store.get_content(i)["kind"] == "video")
    assert video["meta"]["factcheck"]["scenes_kept"] >= 3


def test_edits_on_approval_are_saved_as_corrections(agency):
    cid = agency.director.produce_post("mastodon", "free PDF editors", "tested", link="https://aitoolsprimer.com/pdf")
    original = agency.store.get_content(cid)["body"]
    agency.director.approve(cid, edited_body=original + " Edited by a human.")
    corr = agency.store.list_corrections()
    assert corr and corr[0]["original"] == original and corr[0]["edited"].endswith("Edited by a human.")
    assert agency.store.count_corrections() == 1


def test_team_modes(agency, fake_llm):
    from agency.agents.team import Team
    from agency.agents.writer import Writer

    w2 = Writer(fake_llm, agency.store, agency.settings.brand)
    team = Team(agency.writer, w2, judge=fake_llm, mode="team")
    calls = []
    out = team.compose("post", "bluesky", "brief", lambda w: calls.append(w) or w.post("bluesky", "free PDF editors", "tested"))
    assert len(calls) == 2 and out["text"]
    single = Team(agency.writer, None, judge=fake_llm, mode="team")   # no second writer -> best_of_n
    assert single.mode == "best_of_n"
    batched = team.compose_many([("post", "bluesky", "b", lambda w: w.post("bluesky", "t", "a")), ("post", "mastodon", "b", lambda w: w.post("mastodon", "t", "a"))])
    assert len(batched) == 2
