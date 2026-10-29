#!/bin/bash
# 阶段 0：安装新依赖脚本

echo "========== 后端依赖安装 =========="
cd backend
echo "安装 httpx（HTTP 客户端，用于地理编码 API 调用）"
uv add httpx

echo "安装 reportlab（PDF 报告生成）"
uv add reportlab

echo "安装 python-docx（Word 报告生成）"
uv add python-docx

echo ""
echo "========== 前端依赖安装 =========="
cd ../frontend
echo "安装 echarts（图表库，用于热力图）"
pnpm add echarts

echo "安装 @amap/amap-jsapi-loader（高德地图 JS API）"
pnpm add @amap/amap-jsapi-loader

echo ""
echo "========== 依赖安装完成 =========="
echo "后端新增："
echo "  - httpx: HTTP 客户端"
echo "  - reportlab: PDF 报告生成"
echo "  - python-docx: Word 报告生成"
echo ""
echo "前端新增："
echo "  - echarts: 数据可视化图表库"
echo "  - @amap/amap-jsapi-loader: 高德地图 JS SDK"
