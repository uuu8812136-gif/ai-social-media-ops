from app.integrations.synapse_engine.platforms.builtin import BuiltinPlatformAdapter


def test_kuaishou_restriction_message_is_detected():
    adapter = BuiltinPlatformAdapter("kuaishou")

    reason = adapter._account_restriction_reason(
        "账号已被封禁\n该账号因违规操作已受到限制，无法访问创作者中心"
    )

    assert reason == (
        "快手账号已被封禁或限制使用，当前无法访问创作者中心，"
        "请在快手 App 查看封禁原因并申诉。"
    )


def test_kuaishou_normal_page_is_not_restricted():
    adapter = BuiltinPlatformAdapter("kuaishou")

    assert adapter._account_restriction_reason("作品管理 发布视频 数据中心") is None


def test_restriction_copy_does_not_affect_other_platforms():
    adapter = BuiltinPlatformAdapter("douyin")

    assert adapter._account_restriction_reason("账号已被封禁") is None


def test_kuaishou_shell_is_not_treated_as_publish_workspace():
    adapter = BuiltinPlatformAdapter("kuaishou")

    assert adapter._publish_page_body_is_ready("首页 内容管理 数据中心 页脚") is False
    assert (
        adapter._publish_page_body_is_ready("拖拽视频到此或点击上传\n上传视频") is True
    )


def test_other_platform_ready_body_keeps_generic_fallback():
    adapter = BuiltinPlatformAdapter("douyin")

    assert adapter._publish_page_body_is_ready("正在加载") is False
    assert adapter._publish_page_body_is_ready("发布视频") is True


def test_kuaishou_work_list_extracts_matching_content_and_metrics():
    adapter = BuiltinPlatformAdapter("kuaishou")
    payload = {
        "data": {
            "list": [
                {
                    "workId": "3xhisyc8tgee8bs",
                    "title": "快手私密发布验收 20260714-102327\n测试内容",
                    "playCount": 1,
                    "commentCount": 0,
                    "likeCount": 0,
                }
            ]
        }
    }

    result = adapter._extract_kuaishou_manager_post(
        [payload], title="快手私密发布验收 20260714-102327"
    )

    assert result == {
        "external_post_id": "3xhisyc8tgee8bs",
        "publish_url": "https://www.kuaishou.com/short-video/3xhisyc8tgee8bs",
        "metrics": {"play_count": 1, "comment_count": 0, "like_count": 0},
    }
