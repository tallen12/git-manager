from git_manager.verification.output import OUTPUT_TAIL_LINES, combined_output, tail_lines


def test_the_tail_keeps_the_last_500_lines() -> None:
    text = "".join(f"line {number}\n" for number in range(1, 1001))

    tail = tail_lines(text)

    assert OUTPUT_TAIL_LINES == 500
    assert tail.splitlines()[0] == "line 501"
    assert tail.endswith("line 1000\n")
    assert len(tail.splitlines()) == 500


def test_short_output_is_kept_whole() -> None:
    assert tail_lines("one\ntwo") == "one\ntwo"
    assert tail_lines("") == ""


def test_stderr_follows_stdout_on_its_own_line() -> None:
    assert combined_output("ok\n", "boom\n") == "ok\nboom\n"
    assert combined_output("no newline", "boom\n") == "no newline\nboom\n"
    assert combined_output("", "boom\n") == "boom\n"
    assert combined_output("out", "") == "out"
