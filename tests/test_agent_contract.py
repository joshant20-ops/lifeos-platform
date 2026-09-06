from governor.agent_contract import declares_pass


def test_plain_pass_is_accepted():
    assert declares_pass("RESULT=PASS\n")


def test_ansi_and_tui_framed_pass_is_accepted():
    text = "\x1b[36m│\x1b[0m RESULT=PASS \x1b[36m│\x1b[0m\n"
    assert declares_pass(text)


def test_prompt_contract_echo_is_not_accepted():
    assert not declares_pass("RESULT=PASS|RETRY|BLOCKED\n")


def test_explanatory_prose_is_not_accepted():
    assert not declares_pass("The task would end with RESULT=PASS when complete.\n")
