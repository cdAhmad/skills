#!/bin/bash
set -e

# 自动识别入参前缀，支持任意顺序
TOKEN=""
for arg in "$@"; do
    case "$arg" in
        sk-*)   TOKEN="$arg" ;;
        *)      echo "警告: 无法识别的参数 '$arg'，已跳过" ;;
    esac
done

# TOKEN 兜底：从环境变量读取
[ -z "$TOKEN" ] && TOKEN="$ANTHROPIC_AUTH_TOKEN"

# TOKEN 仍然为空时：已安装 Claude 则沿用已有配置，否则报错
if [ -z "$TOKEN" ]; then
    if command -v claude &>/dev/null; then
        echo "未提供 ANTHROPIC_AUTH_TOKEN，使用已有 Claude Code 配置"
    else
        echo "用法:  /bin/bash $0 [ANTHROPIC_AUTH_TOKEN]"
        echo "示例:  /bin/bash $0 sk-xxxxxxxxxxxx"
        echo ""
        echo "注意: Claude Code 未安装时必须提供 ANTHROPIC_AUTH_TOKEN"
        exit 1
    fi
fi

# 检查 Claude Code：已安装则更新，未安装则安装
if command -v claude &>/dev/null; then
    echo "Claude Code 已安装，执行更新..."
    claude update
else
    echo "Claude Code 未安装，开始安装..."
    curl -fsSL https://claude.ai/install.sh | bash
fi

# 将 DeepSeek 模型配置写入 shell 环境变量（持久化，已存在则覆盖）
SHELL_RC="$HOME/.zshrc"

# 先删除旧的 DeepSeek 配置块
if grep -q "ANTHROPIC_BASE_URL" "$SHELL_RC" 2>/dev/null; then
    sed -i '' '/^# Claude Code - DeepSeek/,/^export CLAUDE_CODE_EFFORT_LEVEL=max$/d' "$SHELL_RC"
fi

cat >> "$SHELL_RC" << EOF
# Claude Code - DeepSeek 模型
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
$( [ -n "$TOKEN" ] && echo "export ANTHROPIC_AUTH_TOKEN=$TOKEN" || echo "# ANTHROPIC_AUTH_TOKEN 已配置，无需重复设置" )
export ANTHROPIC_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]
export ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
export CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash
export CLAUDE_CODE_EFFORT_LEVEL=max
EOF

echo "已将 DeepSeek 模型环境变量写入 $SHELL_RC"

# 将 claude 添加到 PATH（已存在则跳过）
if grep -Fxq 'export PATH="$HOME/.local/bin:$PATH"' "$SHELL_RC"; then
    echo "Claude PATH 已存在，跳过"
else
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
    echo "已将 Claude 添加到 PATH"
fi

# 在当前 shell 中立即生效（无需重启终端）
export PATH="$HOME/.local/bin:$PATH"
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
[ -n "$TOKEN" ] && export ANTHROPIC_AUTH_TOKEN="$TOKEN"
export ANTHROPIC_MODEL="deepseek-v4-pro[1m]"
export ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro[1m]"
export ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-pro[1m]"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-flash"
export CLAUDE_CODE_SUBAGENT_MODEL="deepseek-v4-flash"
export CLAUDE_CODE_EFFORT_LEVEL="max"

echo "Claude Code + DeepSeek 环境已配置完成（当前 shell 已生效）"
