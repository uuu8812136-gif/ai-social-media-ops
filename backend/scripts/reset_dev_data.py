"""一键重置开发数据脚本。

用法：cd backend && python -m scripts.reset_dev_data
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import AsyncSessionLocal
from app.models import Account, AssetLibrary, City, Content, ContentCalendar, Dealer, KnowledgeChunk, KnowledgeDocument, Lead, LeadFollowup, RiskCheckHistory, RiskWord, User
from app.core.seed import seed_data


async def reset_all():
    """Drop all data and re-seed."""
    print("⚠️  即将删除所有数据并重新生成开发数据...")

    async with AsyncSessionLocal() as db:
        try:
            # Delete in reverse dependency order
            tables = [
                (LeadFollowup, "lead_followups"),
                (RiskCheckHistory, "risk_check_history"),
                (ContentCalendar, "content_calendar"),
                (Lead, "leads"),
                (AssetLibrary, "asset_library"),
                (Content, "contents"),
                (KnowledgeChunk, "knowledge_chunks"),
                (KnowledgeDocument, "knowledge_documents"),
                (RiskWord, "risk_words"),
                (Account, "accounts"),
                (Dealer, "dealers"),
                (City, "cities"),
                (User, "users"),
            ]

            for model, table_name in tables:
                from sqlalchemy import delete
                result = await db.execute(delete(model))
                print(f"  删除 {table_name}: {result.rowcount} 条")

            await db.commit()
            print("\n✅ 数据已清空，开始重新生成...\n")
        except Exception as e:
            await db.rollback()
            print(f"\n❌ 清空失败: {e}")
            raise

    # Re-seed
    await seed_data()

    print("\n✅ 开发数据已重新生成！")
    print("\n测试账号：")
    print("  admin / admin123 (管理员)")
    print("  operator / operator123 (运营)")
    print("  dealer / dealer123 (经销商)")


if __name__ == "__main__":
    asyncio.run(reset_all())
