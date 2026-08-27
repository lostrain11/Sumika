import tempfile
import unittest
from pathlib import Path

from check_docs import (
    check_archived_references,
    check_current_execution,
    check_local_links,
    check_status_matrix,
)


class DocumentationCheckerTests(unittest.TestCase):
    def write(self, root: Path, relative: str, content: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_valid_link_and_code_block_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "docs/README.md", "[target](target.md)\n")
            self.write(root, "docs/target.md", "# Target\n")
            self.write(root, "docs/example.md", "```text\n[missing](missing.md)\n```\n")
            self.assertEqual(check_local_links(root), [])

    def test_broken_local_link_reports_file_and_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "docs/README.md", "[missing](missing.md)\n")
            errors = check_local_links(root)
            self.assertEqual(len(errors), 1)
            self.assertIn("docs/README.md:1", errors[0])
            self.assertIn("missing.md", errors[0])

    def test_status_matrix_requires_columns_and_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "docs/status-matrix.md", "# Status\n\n| ID | 状态 |\n| --- | --- |\n")
            errors = check_status_matrix(root)
            self.assertTrue(any("expected columns" in error for error in errors))

    def test_archived_document_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "deprecated/20260101/docs/old.md", "# Old\n")
            self.write(root, "docs/README.md", "旧文档 old.md\n")
            errors = check_archived_references(root)
            self.assertEqual(len(errors), 1)
            self.assertIn("old.md", errors[0])

    def test_runtime_dependency_readme_is_not_treated_as_product_doc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "deprecated/20260101/profile/node_modules/pkg/README.md", "# Dependency\n")
            self.write(root, "docs/README.md", "README.md is a normal filename\n")
            self.assertEqual(check_archived_references(root), [])

    def valid_current_execution(self) -> str:
        headings = [
            "# Sumika 当前执行契约",
            "## 目标",
            "## Definition of Done",
            "## 当前基线",
        ]
        baseline = [
            "- Branch: `test`",
            "- Baseline commit: `abc1234`",
            "- Last verified commit: `abc1234`",
        ]
        tail = [
            "## 当前里程碑",
            "## 接下来的三个动作",
            "1. First",
            "2. Second",
            "3. Third",
            "## 固定决策",
            "## 明确暂缓",
            "## 当前阻塞",
            "## 验证记录",
            "## 恢复顺序",
            "## 更新规则",
        ]
        return "\n\n".join(headings + baseline + tail) + "\n"

    def test_current_execution_contract_accepts_required_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "docs/current-execution.md", self.valid_current_execution())
            self.assertEqual(check_current_execution(root), [])

    def test_current_execution_contract_requires_three_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content = self.valid_current_execution().replace("3. Third\n", "")
            self.write(root, "docs/current-execution.md", content)
            errors = check_current_execution(root)
            self.assertTrue(any("exactly numbered items" in error for error in errors))

    def test_current_execution_contract_rejects_sensitive_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content = self.valid_current_execution() + "C:\\Users\\someone\\secret\n"
            self.write(root, "docs/current-execution.md", content)
            errors = check_current_execution(root)
            self.assertTrue(any("Windows user path" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
