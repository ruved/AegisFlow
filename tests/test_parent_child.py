from aegisflow.rag.parent_child import approximate_token_count, parent_child_chunks


def test_parent_child_ids_offsets_and_heading_are_consistent():
    text = "# Pool incidents\n\nERR_POOL_01 means connections are exhausted."

    parents, children = parent_child_chunks(
        text, "incidents.md", parent_tokens=100, child_tokens=5
    )

    assert len(parents) == 1
    assert parents[0].heading == "Pool incidents"
    assert children
    assert all(child.parent_id == parents[0].parent_id for child in children)
    for child in children:
        assert parents[0].text[child.parent_start : child.parent_end] == child.text
        assert child.chunk_id.startswith(f"{parents[0].parent_id}::child-")
    assert approximate_token_count(parents[0].text) <= 100


def test_headings_define_parent_sections_and_stay_with_section_text():
    text = "# First\n\nA short section.\n\n# Second\n\nAnother short section."

    parents, _ = parent_child_chunks(
        text, "sections.md", parent_tokens=10, child_tokens=20
    )

    assert [parent.heading for parent in parents] == ["First", "Second"]
    assert "A short section." in parents[0].text
    assert "Another short section." in parents[1].text


def test_oversized_code_blocks_and_markdown_tables_remain_intact():
    code = "```python\n" + "print('still whole')\n" * 4 + "```"
    table = "| name | value |\n| --- | --- |\n| pool | exhausted |"

    code_parents, code_children = parent_child_chunks(
        code, "code.md", parent_tokens=2, child_tokens=1
    )
    table_parents, table_children = parent_child_chunks(
        table, "table.md", parent_tokens=2, child_tokens=1
    )

    assert len(code_parents) == len(code_children) == 1
    assert code_parents[0].text == code_children[0].text == code
    assert len(table_parents) == len(table_children) == 1
    assert table_parents[0].text == table_children[0].text == table


def test_oversized_prose_splits_into_multiple_children():
    text = "A sentence with several words that should split near the configured limit."

    parents, children = parent_child_chunks(
        text, "notes.md", parent_tokens=100, child_tokens=4
    )

    assert len(parents) == 1
    assert len(children) > 1
    assert "".join(child.text for child in children).replace(" ", "") in text.replace(
        " ", ""
    )
