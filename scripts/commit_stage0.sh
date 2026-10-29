#!/bin/bash
# 阶段 0 提交脚本

echo "========== 阶段 0 提交脚本 =========="
echo ""

# 添加所有改动
echo "1. 添加所有改动到暂存区..."
git add .

# 查看状态
echo ""
echo "2. 查看即将提交的文件..."
git status --short

# 提交
echo ""
echo "3. 提交改动..."
git commit -m "chore(stage0): 完成阶段 0 准备工作

- 创建目录结构：inspector/manager 双端页面、analytics 服务目录、scripts 脚本目录
- 配置环境变量：新增高德地图 API、简化工作流开关、数据聚合缓存配置
- 准备依赖安装：创建一键安装脚本和前端依赖清单
- 新增文档：改造实施方案、阶段 0 完成清单

待执行：bash scripts/install_dependencies.sh 安装新依赖"

# 显示最新提交
echo ""
echo "4. 最新提交信息："
git log -1 --oneline --decorate

# 推送（可选）
echo ""
echo "========== 提交完成 =========="
echo ""
echo "如果需要推送到远程仓库，请执行："
echo "  git push origin main"
echo ""
echo "下一步："
echo "  1. 执行依赖安装：bash scripts/install_dependencies.sh"
echo "  2. 或者直接告诉我：\"开始阶段 1\""
