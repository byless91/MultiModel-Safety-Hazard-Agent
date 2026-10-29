"""阶段 2：后端核心服务测试

测试分类服务、地理编码服务、数据聚合服务、简化工作流
"""
import pytest

from app.core.db import SessionLocal
from app.models.entities import Assessment, new_id, utcnow
from app.services.analytics import get_benchmark_data, get_heatmap_data, get_trends_data
from app.services.classification import (
    _fallback_rule_based_classification,
    classify_hazard,
    recommend_regulations,
)
from app.services.geocoding import batch_geocode, geocode_address
from app.services.simple_workflow import run_classification_workflow


class TestClassificationService:
    """测试分类服务"""

    @pytest.mark.asyncio
    async def test_fallback_classification(self):
        """测试兜底规则分类"""
        # 消防隐患
        result = _fallback_rule_based_classification("楼道堆放易燃物品，疏散通道堵塞")
        assert result["suggested_category"] == "消防隐患"
        assert result["confidence"] > 0.5
        assert len(result["keywords"]) > 0

        # 生产安全
        result = _fallback_rule_based_classification("设备故障，缺少防护措施")
        assert result["suggested_category"] == "生产安全"

        # 无法判断
        result = _fallback_rule_based_classification("这是一段普通的描述")
        assert result["suggested_category"] == "其他"
        assert result["confidence"] < 0.5

    @pytest.mark.asyncio
    async def test_recommend_regulations(self):
        """测试法规推荐"""
        regulations = await recommend_regulations(
            category="消防隐患",
            subcategory="堵塞疏散通道",
            description="楼道堆放杂物",
            top_k=5,
        )
        # 返回列表
        assert isinstance(regulations, list)
        # 每项包含必需字段
        if regulations:
            assert "text" in regulations[0]
            assert "source" in regulations[0]


class TestGeocodingService:
    """测试地理编码服务"""

    @pytest.mark.asyncio
    async def test_geocode_address(self):
        """测试单个地址地理编码"""
        # 注意：需要配置 AMAP_API_KEY 才能通过
        result = await geocode_address("重庆市渝北区龙溪街道红石路88号", city="重庆")

        # 如果没有配置 API Key，返回 None
        if result is None:
            pytest.skip("未配置高德地图 API Key")

        # 验证结果
        assert "longitude" in result
        assert "latitude" in result
        assert "district" in result
        assert isinstance(result["longitude"], float)
        assert isinstance(result["latitude"], float)

    @pytest.mark.asyncio
    async def test_batch_geocode(self):
        """测试批量地理编码"""
        addresses = [
            {"id": "1", "address": "重庆市渝北区龙溪街道", "city": "重庆"},
            {"id": "2", "address": "重庆市江北区观音桥", "city": "重庆"},
        ]

        results = await batch_geocode(addresses, delay_seconds=0.1)

        # 返回结果数量一致
        assert len(results) == len(addresses)

        # 每项包含必需字段
        for item in results:
            assert "id" in item
            assert "address" in item
            assert "success" in item


class TestAnalyticsService:
    """测试数据分析服务"""

    def setup_method(self):
        """准备测试数据"""
        db = SessionLocal()
        try:
            # 插入测试数据
            test_assessments = [
                Assessment(
                    id=new_id(),
                    description="测试隐患1",
                    address="重庆市渝北区龙溪街道",
                    longitude=106.550464,
                    latitude=29.563761,
                    district="渝北区",
                    street="龙溪街道",
                    hazard_category="消防隐患",
                    risk_level=1,
                    confirmed=True,
                    status="completed",
                    created_at=utcnow(),
                ),
                Assessment(
                    id=new_id(),
                    description="测试隐患2",
                    address="重庆市渝北区龙溪街道",
                    longitude=106.551,
                    latitude=29.564,
                    district="渝北区",
                    street="龙溪街道",
                    hazard_category="生产安全",
                    risk_level=2,
                    confirmed=True,
                    status="completed",
                    created_at=utcnow(),
                ),
            ]
            for assessment in test_assessments:
                db.add(assessment)
            db.commit()
        finally:
            db.close()

    def test_get_heatmap_data(self):
        """测试热力图数据"""
        db = SessionLocal()
        try:
            data = get_heatmap_data(db, district="渝北区")

            # 返回列表
            assert isinstance(data, list)

            # 如果有数据，验证格式
            if data:
                item = data[0]
                assert "district" in item
                assert "longitude" in item
                assert "latitude" in item
                assert "count" in item
                assert "level_1" in item
        finally:
            db.close()

    def test_get_benchmark_data(self):
        """测试对标分析"""
        db = SessionLocal()
        try:
            result = get_benchmark_data(db, district="渝北区")

            # 验证返回格式
            assert "district" in result
            assert "total" in result
            assert "categories" in result
            assert "city_avg" in result
            assert "rank" in result
            assert "total_districts" in result

            # 数值验证
            assert isinstance(result["total"], int)
            assert isinstance(result["rank"], int)
        finally:
            db.close()

    def test_get_trends_data(self):
        """测试趋势数据"""
        db = SessionLocal()
        try:
            data = get_trends_data(db, district="渝北区", months=6)

            # 返回列表
            assert isinstance(data, list)

            # 如果有数据，验证格式
            if data:
                item = data[0]
                assert "month" in item
                assert "count" in item
                assert "level_1" in item
        finally:
            db.close()


class TestSimpleWorkflow:
    """测试简化工作流"""

    @pytest.mark.asyncio
    async def test_run_classification_workflow(self):
        """测试分类工作流"""
        result = await run_classification_workflow(
            description="楼道堆放易燃物品，疏散通道堵塞",
            images=[],
            ocr_texts=None,
        )

        # 验证返回格式
        assert "classification" in result
        assert "recommended_regulations" in result
        assert "status" in result

        # 验证分类结果
        classification = result["classification"]
        assert "suggested_category" in classification
        assert "confidence" in classification


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
