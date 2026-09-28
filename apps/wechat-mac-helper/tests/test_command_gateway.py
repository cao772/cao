"""Check owner-only intake, deduplication and command execution boundaries."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT))
spec = importlib.util.spec_from_file_location("command_gateway", SCRIPT / "command_gateway.py")
assert spec and spec.loader
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class Reader:
    def __init__(self, messages):
        self.messages = messages

    def _get(self, route, *, params):
        assert route == "/api/v1/chatlog"
        assert params["talker"] == "filehelper"
        return {"messages": self.messages}


class CommandGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = gateway.open_database(Path(self.temp.name) / "commands.sqlite3")

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_owner_can_search_across_projects_with_source(self):
        self.assertTrue(gateway.accept_message({"isSender": True, "type": "普通文本", "content": "/搜索 框架"}))
        self.assertFalse(gateway.accept_message({"isSender": False, "type": "普通文本", "content": "/搜索 框架"}))
        payload = {"count": 1, "conversation_available": True, "results": [{
            "project_id": "hy-claw", "project_name": "HY Claw", "source_type": "material",
            "source_name": "项目概览.md", "source_path": "management/项目概览.md",
            "source_time": "2026-09-24T00:00:00Z", "snippet": "框架分支为 ts-dev",
        }]}
        with patch.object(gateway, "_json_request", return_value=payload) as request:
            reply = gateway.execute("/搜索 框架")
        self.assertIn("HY Claw", reply)
        self.assertIn("management/项目概览.md", reply)
        request.assert_called_once()
        self.assertIn("/api/v1/search?", request.call_args.args[0])

    def test_only_own_command_is_ingested_once(self):
        messages = [
            {"serverId": "1", "createTime": 1000, "content": "/项目 列表", "type": "普通文本", "isSender": True},
            {"serverId": "2", "createTime": 1000, "content": "/执行 删除文件", "type": "普通文本", "isSender": False},
            {"serverId": "3", "createTime": 1000, "content": "【项目助手】\n回复", "type": "普通文本", "isSender": True},
            {"serverId": "4", "createTime": 1000, "content": "/状态无效", "type": "普通文本", "isSender": True},
        ]
        reader = Reader(messages)
        self.assertEqual(gateway.ingest(self.conn, reader, now=1010), 1)
        self.assertEqual(gateway.ingest(self.conn, reader, now=1011), 0)
        self.assertEqual(self.conn.execute("SELECT command FROM commands").fetchone()[0], "/项目 列表")

    def test_actions_wait_for_sender_and_expire(self):
        self.conn.execute("INSERT INTO commands(message_id,created_at,command) VALUES('1',1000,'/执行 处理项目')")
        self.conn.commit()
        with patch.object(gateway, "execute") as execute:
            self.assertEqual(gateway.process_pending(self.conn, sender_ready=False, now=1010), 0)
            execute.assert_not_called()
            self.assertEqual(gateway.process_pending(self.conn, sender_ready=True, now=1700), 1)
            execute.assert_not_called()
        row = self.conn.execute("SELECT status,reply FROM commands WHERE message_id='1'").fetchone()
        self.assertEqual(row["status"], "awaiting_send")
        self.assertIn("超过 10 分钟", row["reply"])

    def test_processed_command_is_not_repeated(self):
        self.conn.execute("INSERT INTO commands(message_id,created_at,command) VALUES('1',1000,'/项目 列表')")
        self.conn.commit()
        with patch.object(gateway, "execute", return_value="四个项目") as execute:
            self.assertEqual(gateway.process_pending(self.conn, now=1010), 1)
            self.assertEqual(gateway.process_pending(self.conn, now=1011), 0)
            execute.assert_called_once()
        row = self.conn.execute("SELECT status,reply FROM commands").fetchone()
        self.assertEqual(dict(row), {"status": "awaiting_send", "reply": "四个项目"})

    def test_question_only_sends_matching_project_facts(self):
        key_file = Path(self.temp.name) / "deepseek-api-key"
        key_file.write_text("test-key", encoding="utf-8")
        calls = []

        def request(url, *, token=None, body=None):
            calls.append((url, token, body))
            if url.endswith("/brief"):
                return {"current_stage": "验证", "issues": ["需核验模型"]}
            if url.endswith("/intelligence"):
                return {
                    "profile": {"description": "电力设备缺陷处置", "repositories": [{"id": "defect", "url": "https://example.invalid/defect"}]},
                    "context": {"available": True, "project": {"purpose": "巡检缺陷分级"}},
                    "materials": [{"name": "最新评测报告.pdf", "path": "材料/最新评测报告.pdf",
                                   "version_status": "current", "summary": "已完成验证"}],
                }
            return {"choices": [{"message": {"content": "缺陷项目处于验证阶段。"}}]}

        projects = [
            {"project_id": "low-voltage", "project_name": "低电压项目"},
            {"project_id": "power-defect-agent", "project_name": "缺陷项目"},
        ]
        with patch.object(gateway, "DEEPSEEK_KEY_FILE", key_file), patch.object(gateway, "_projects", return_value=projects), patch.object(gateway, "_json_request", side_effect=request):
            answer = gateway.project_question("/问 缺陷项目有什么问题？")
        self.assertIn("缺陷项目处于验证阶段。", answer)
        self.assertIn("依据：本机研发平台项目简报与项目认知 power-defect-agent", answer)
        self.assertEqual(len(calls), 3)
        self.assertIn("power-defect-agent/brief", calls[0][0])
        self.assertIn("power-defect-agent/intelligence", calls[1][0])
        self.assertNotIn("low-voltage", str(calls))
        self.assertEqual(calls[2][1], "test-key")
        self.assertEqual(calls[2][2]["model"], "deepseek-flash")
        question_payload = calls[2][2]["messages"][1]["content"]
        self.assertIn("最新评测报告.pdf", question_payload)
        self.assertIn("https://example.invalid/defect", question_payload)

    def test_mobile_answer_cuts_at_line_and_marks_truncation(self):
        text = "甲" * 40 + "\n" + "乙" * 40 + "\n" + "丙" * 40
        answer = gateway._mobile_reply(text, limit=90)
        self.assertEqual(answer.splitlines()[0], "甲" * 40)
        self.assertEqual(answer.splitlines()[1], "乙" * 40)
        self.assertIn("已截取", answer)
        self.assertNotIn("丙", answer)

    def test_project_search_returns_material_and_wechat_sources(self):
        projects = [{"project_id": "hy-claw", "project_name": "HY CLAW 内研"}]

        def request(url, *, token=None, body=None):
            self.assertIn("/hy-claw/search?", url)
            return {
                "count": 2, "material_count": 1, "communication_count": 1,
                "results": [{"material": {"name": "需求清单.xlsx", "path": "资料/需求清单.xlsx",
                                           "material_type_label": "需求与需求说明"},
                             "locator": "Sheet1 A3", "snippet": "新增项目进度查询"}],
                "communications": [{"conversation_name": "HY CLAW 内研", "observed_at": "2026-09-27T10:30:00+08:00",
                                    "text": "项目进度查询已确认"}],
            }

        with patch.object(gateway, "_projects", return_value=projects), patch.object(gateway, "_json_request", side_effect=request):
            reply = gateway.project_command("/项目 HY CLAW 内研 搜索 项目进度")
        self.assertIn("需求清单.xlsx", reply)
        self.assertIn("Sheet1 A3", reply)
        self.assertIn("来源：资料/需求清单.xlsx", reply)
        self.assertIn("HY CLAW 内研 · 2026-09-27 10:30", reply)
        self.assertIn("项目进度查询已确认", reply)

    def test_project_background_and_materials_use_intelligence(self):
        projects = [{"project_id": "low-voltage", "project_name": "低电压治理"}]
        intelligence = {
            "profile": {"description": "配网低电压治理审查", "repositories": [{"id": "low-voltage", "provider": "GitLab",
                                                                  "branch": "main", "head": "abcdef1234567890",
                                                                  "url": "https://oauth2:secret@example.invalid/repo?token=secret"}]},
            "context": {"project": {"current_stage": "测试与验证"}},
            "summary": {"material_count": 2},
            "materials": [
                {"name": "新版可研.pdf", "path": "资料/新版可研.pdf", "modified_at": "2026-09-27",
                 "material_type_label": "需求与需求说明", "version_status": "current", "summary": "新增了审查说明"},
                {"name": "旧版可研.pdf", "version_status": "historical"},
            ],
        }
        with patch.object(gateway, "_projects", return_value=projects), patch.object(gateway, "_json_request", return_value=intelligence):
            background = gateway.project_command("/项目 低电压 背景")
            materials = gateway.project_command("/项目 低电压 材料")
            repositories = gateway.project_command("/项目 低电压 仓库")
        self.assertIn("配网低电压治理审查", background)
        self.assertIn("https://example.invalid/repo", background)
        self.assertNotIn("secret", background)
        self.assertIn("新版可研.pdf", materials)
        self.assertNotIn("旧版可研.pdf", materials)
        self.assertIn("GitLab · main · abcdef123456", repositories)
        self.assertIn("https://example.invalid/repo", repositories)
        self.assertNotIn("secret", repositories)

    def test_model_facts_strip_repository_credentials(self):
        with patch.object(gateway, "_json_request", return_value={
            "profile": {"repositories": [{"url": "https://user:secret@example.invalid/repo?token=secret"}]},
            "context": {}, "materials": [],
        }):
            facts = gateway._intelligence_facts("hy-claw")
        self.assertEqual(facts["repositories"][0]["url"], "https://example.invalid/repo")

    def test_send_is_only_confirmed_by_personal_chatlog(self):
        self.conn.execute(
            "INSERT INTO commands(message_id,created_at,command,status,reply,delivered_at) "
            "VALUES('1',1000,'/状态','send_requested','正常',1010)"
        )
        self.conn.commit()
        expected = gateway.PREFIX + "\n正常"
        self.assertEqual(gateway.confirm_sent(self.conn, Reader([])), 0)
        self.assertEqual(gateway.confirm_sent(self.conn, Reader([{
            "isSender": True, "content": expected, "createTime": 1012,
        }])), 1)
        self.assertEqual(self.conn.execute("SELECT status FROM commands").fetchone()[0], "sent")

    def test_onebot_acceptance_does_not_trigger_duplicate_send(self):
        self.conn.execute(
            "INSERT INTO commands(message_id,created_at,command,status,reply) "
            "VALUES('1',1000,'/状态','awaiting_send','正常')"
        )
        self.conn.commit()
        with patch.object(gateway, "personal_sender_ready", return_value=True), patch.object(
            gateway, "_json_request", return_value={"status": "ok"}
        ) as request:
            self.assertEqual(gateway.deliver_pending(self.conn, "test-token"), 1)
            self.assertEqual(gateway.deliver_pending(self.conn, "test-token"), 0)
            request.assert_called_once()
        self.assertEqual(self.conn.execute("SELECT status FROM commands").fetchone()[0], "send_requested")

    def test_bot_reply_uses_fixed_recipient_and_deduplicates(self):
        binding = Path(self.temp.name) / "recipient.json"
        binding.write_text(json.dumps({"userId": "owner@im.wechat", "accountId": "bot@im.bot"}))
        self.conn.execute(
            "INSERT INTO commands(message_id,created_at,command,status,reply) "
            "VALUES('1',1000,'/状态','awaiting_send','正常')"
        )
        self.conn.commit()

        def request(url, *, token=None, body=None):
            if url.endswith("/status"):
                return {"hub": "online", "connector": "online", "accountId": "bot@im.bot"}
            self.assertEqual(body["to"], "owner@im.wechat")
            return {"success": True, "status": "sent"}

        with patch.object(gateway, "BOT_RECIPIENT_FILE", binding), patch.object(gateway, "_json_request", side_effect=request) as send:
            recipient = gateway.bot_recipient("token")
            self.assertEqual(recipient, "owner@im.wechat")
            self.assertEqual(gateway.deliver_pending_bot(self.conn, "token", recipient), 1)
            self.assertEqual(gateway.deliver_pending_bot(self.conn, "token", recipient), 0)
            self.assertEqual(send.call_count, 2)
        self.assertEqual(self.conn.execute("SELECT status FROM commands").fetchone()[0], "sent_bot")

    def test_explicit_bot_rejection_retries_with_backoff_and_limit(self):
        self.conn.execute(
            "INSERT INTO commands(message_id,created_at,command,status,reply) "
            "VALUES('1',1000,'/状态','awaiting_send','正常')"
        )
        self.conn.commit()
        with patch.object(gateway, "_json_request", return_value={"success": False, "status": "rejected"}) as request, \
                patch.object(gateway.time, "time", return_value=2000):
            self.assertEqual(gateway.deliver_pending_bot(self.conn, "token", "owner@im.wechat"), 0)
            self.assertEqual(gateway.deliver_pending_bot(self.conn, "token", "owner@im.wechat"), 0)
            request.assert_called_once()
        with patch.object(gateway, "_json_request", return_value={"success": False, "status": "rejected"}) as request, \
                patch.object(gateway.time, "time", return_value=2061):
            self.assertEqual(gateway.deliver_pending_bot(self.conn, "token", "owner@im.wechat"), 0)
            request.assert_called_once()
        with patch.object(gateway, "_json_request", return_value={"success": False, "status": "rejected"}) as request, \
                patch.object(gateway.time, "time", return_value=2122):
            self.assertEqual(gateway.deliver_pending_bot(self.conn, "token", "owner@im.wechat"), 0)
            request.assert_called_once()
        with patch.object(gateway, "_json_request", return_value={"success": True, "status": "sent"}) as request, \
                patch.object(gateway.time, "time", return_value=2200):
            self.assertEqual(gateway.deliver_pending_bot(self.conn, "token", "owner@im.wechat"), 0)
            request.assert_not_called()
        row = self.conn.execute("SELECT status,attempts FROM commands WHERE message_id='1'").fetchone()
        self.assertEqual((row["status"], row["attempts"]), ("bot_failed", 3))

    def test_existing_queue_gets_attempts_column_without_losing_commands(self):
        path = Path(self.temp.name) / "old.sqlite3"
        with sqlite3.connect(path) as old:
            old.execute("CREATE TABLE commands (message_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, command TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reply TEXT, delivered_at INTEGER, error TEXT)")
            old.execute("INSERT INTO commands(message_id,created_at,command) VALUES('old',1000,'/项目 列表')")
        with gateway.open_database(path) as migrated:
            row = migrated.execute("SELECT command,attempts FROM commands WHERE message_id='old'").fetchone()
            self.assertEqual((row["command"], row["attempts"]), ("/项目 列表", 0))

    def test_http_rejection_is_retryable_but_server_error_is_uncertain(self):
        self.conn.execute("INSERT INTO commands(message_id,created_at,command,status,reply) VALUES('1',1000,'/状态','awaiting_send','正常')")
        self.conn.commit()
        rejected = gateway.urllib.error.HTTPError("http://127.0.0.1", 429, "rate limited", {}, None)
        with patch.object(gateway, "_json_request", side_effect=rejected):
            self.assertEqual(gateway.deliver_pending_bot(self.conn, "token", "owner@im.wechat"), 0)
        self.assertEqual(self.conn.execute("SELECT status FROM commands WHERE message_id='1'").fetchone()[0], "bot_failed")

        self.conn.execute("UPDATE commands SET status='awaiting_send' WHERE message_id='1'")
        self.conn.commit()
        uncertain = gateway.urllib.error.HTTPError("http://127.0.0.1", 500, "server error", {}, None)
        with patch.object(gateway, "_json_request", side_effect=uncertain):
            with self.assertRaises(gateway.urllib.error.HTTPError):
                gateway.deliver_pending_bot(self.conn, "token", "owner@im.wechat")
        self.assertEqual(self.conn.execute("SELECT status FROM commands WHERE message_id='1'").fetchone()[0], "bot_requested")


if __name__ == "__main__":
    unittest.main()
