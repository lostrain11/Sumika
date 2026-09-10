import unittest

from sumika_core.projects import ConversationPageError, paginate_turns


def message(message_id, role, content):
    return {
        "id": message_id,
        "role": role,
        "content": content,
        "created_at": f"2026-09-09T00:{message_id[-2:]}:00Z",
    }


def conversation(turn_count):
    messages = [message("leading-tool", "tool", "ignored before first user")]
    for index in range(1, turn_count + 1):
        suffix = f"{index:02d}"
        messages.extend([
            message(f"user-{suffix}", "user", f"question {index}"),
            message(f"assistant-{suffix}-a", "assistant", {"part": 1}),
            message(f"tool-{suffix}", "tool", {"result": index}),
            message(f"assistant-{suffix}-b", "assistant", {"part": 2}),
        ])
    return messages


class ConversationPaginationTests(unittest.TestCase):
    def test_initial_page_is_three_user_started_turns_with_tool_messages(self):
        page = paginate_turns(conversation(15))

        self.assertEqual([turn["id"] for turn in page["turns"]], ["user-13", "user-14", "user-15"])
        self.assertEqual(page["next_before"], "user-13")
        self.assertTrue(page["has_more"])
        self.assertEqual(
            [item["role"] for item in page["turns"][0]["messages"]],
            ["user", "assistant", "tool", "assistant"],
        )

    def test_cursor_page_remains_stable_when_new_turns_arrive(self):
        original = conversation(15)
        first = paginate_turns(original)
        concurrent = original + conversation(17)[-8:]

        older_before_append = paginate_turns(original, before=first["next_before"])
        older_after_append = paginate_turns(concurrent, before=first["next_before"])

        expected = [f"user-{index:02d}" for index in range(3, 13)]
        self.assertEqual([turn["id"] for turn in older_before_append["turns"]], expected)
        self.assertEqual(older_after_append, older_before_append)
        self.assertEqual(older_after_append["next_before"], "user-03")

    def test_cursor_can_be_any_stable_message_inside_a_turn(self):
        messages = conversation(5)
        page = paginate_turns(messages, before="tool-04", limit=2)
        self.assertEqual([turn["id"] for turn in page["turns"]], ["user-02", "user-03"])
        self.assertEqual(page["next_before"], "user-02")

    def test_duplicate_message_ids_are_deduplicated_without_splitting_turns(self):
        messages = conversation(4)
        messages.insert(6, dict(messages[5]))
        page = paginate_turns(messages, limit=4)

        ids = [item["id"] for turn in page["turns"] for item in turn["messages"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([turn["id"] for turn in page["turns"]], ["user-01", "user-02", "user-03", "user-04"])

    def test_incomplete_turn_is_kept_and_bad_cursor_fails_closed(self):
        messages = conversation(2) + [message("user-03", "user", "still waiting")]
        page = paginate_turns(messages)
        self.assertEqual(page["turns"][-1]["messages"], [message("user-03", "user", "still waiting")])
        with self.assertRaises(ConversationPageError):
            paginate_turns(messages, before="missing")


if __name__ == "__main__":
    unittest.main()
