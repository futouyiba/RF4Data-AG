"""
LLM 客户端
=========
调用 OpenAI 兼容 API（GLM-4 / DeepSeek / GPT-4o）生成拟人化钓鱼日志。

P0 策略: 便宜模型 (GLM/DeepSeek) 用于日志生成，强模型仅在分析阶段使用。
支持任何 OpenAI 兼容的 API 端点。
"""

import json
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    logger.warning("openai 库未安装。LLM 功能不可用。建议: pip install openai")


# ── System Prompts ───────────────────────────────────────

SINGLE_CATCH_PROMPT = """\
你是一位经验丰富的 RF4 老钓手和数据研究员。
根据提供的单条渔获数据（含天气、饵料、鱼种、重量），写一句简短的分析日志。
要求：
- 像资深玩家写日记一样，有洞察力
- 如果是奖杯鱼，允许表达兴奋
- 必须引用具体数据（如重量、温度）
- 一句话，不超过 80 字
- 中文输出"""

SESSION_SUMMARY_PROMPT = """\
你是一位经验丰富的 RF4 老钓手和数据分析师。
根据提供的 Session 统计摘要（JSON），写一段 150-200 字的"垂钓心得"。
要求：
- 像老手写日记的语气，有分析有感悟
- 必须引用具体数据（如 CPUE、p50 TTB、最佳饵料、鱼种占比）
- 如果有奖杯鱼要提一嘴
- 对数据趋势做简单分析和建议
- 中文输出"""


class LLMClient:
    """
    OpenAI 兼容 LLM 客户端。

    支持 GLM-4 / DeepSeek / GPT-4o 等任何 OpenAI 兼容 API。
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        temperature: float = 0.8,
        max_tokens: int = 300,
    ):
        if not _HAS_OPENAI:
            raise RuntimeError("openai 库未安装")

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        self._client = OpenAI(
            api_key=api_key or "sk-placeholder",
            base_url=base_url,
        )
        logger.info("LLM 客户端已初始化: %s @ %s", model, base_url)

    def _call(self, system_prompt: str, user_content: str) -> Optional[str]:
        """调用 LLM API。"""
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            text = response.choices[0].message.content.strip()
            logger.debug("LLM 响应 (%d tokens): %s", len(text), text[:80])
            return text
        except Exception as e:
            logger.error("LLM API 调用失败: %s", e)
            return None

    # ── 业务接口 ─────────────────────────────────────────

    def generate_catch_log(self, catch_data: dict) -> Optional[str]:
        """
        为单条渔获生成一句分析日志。

        Args:
            catch_data: {
                "fish_name": str, "weight_g": float, "rod_slot": int,
                "bait": str, "hook_size": str,
                "weather": str, "trophy": bool, ...
            }
        """
        user_content = json.dumps(catch_data, ensure_ascii=False, indent=2)
        return self._call(SINGLE_CATCH_PROMPT, user_content)

    def generate_session_summary(self, stats: dict) -> Optional[str]:
        """
        为整个 Session 生成一段垂钓心得。

        Args:
            stats: get_session_stats() 的返回值，可附加 TTB / 鱼种分布等
        """
        user_content = json.dumps(stats, ensure_ascii=False, indent=2)
        return self._call(SESSION_SUMMARY_PROMPT, user_content)

    def generate_fishing_log(self, session_summary_json: str) -> Optional[str]:
        """
        通用接口：传入 JSON 字符串生成垂钓日志。

        兼容 Gemini PRD 中定义的接口。
        """
        return self._call(SESSION_SUMMARY_PROMPT, session_summary_json)


class MockLLMClient:
    """
    模拟 LLM 客户端（不需要 API key，用于测试和离线场景）。
    生成基于模板的简单日志。
    """

    def generate_catch_log(self, catch_data: dict) -> str:
        name = catch_data.get("fish_name", "未知鱼种")
        weight = catch_data.get("weight_g", 0)
        bait = catch_data.get("bait", "未知饵料")
        trophy = catch_data.get("trophy", False)

        if trophy:
            return f"🏆 奖杯 {name}！{weight:.0f}g，{bait} 立大功！"
        elif weight > 2000:
            return f"大物 {name} {weight:.0f}g 上岸，{bait} 表现不错。"
        else:
            return f"{name} {weight:.0f}g，{bait} 起鱼，正常发挥。"

    def generate_session_summary(self, stats: dict) -> str:
        catch = stats.get("total_catch", 0)
        loss = stats.get("total_loss", 0)
        hours = stats.get("duration_hours", 0)
        cpue = stats.get("cpue_fish_per_hour", 0)

        if catch == 0:
            return f"挂机 {hours:.1f} 小时，颗粒无收。可能需要换点位或饵料。"

        lines = [f"今日作业 {hours:.1f} 小时，起鱼 {catch} 条"]
        if loss > 0:
            lines.append(f"跑鱼 {loss} 次")
        lines.append(f"CPUE {cpue:.1f} 条/时。")

        if cpue > 10:
            lines.append("效率很高，继续保持。")
        elif cpue > 5:
            lines.append("中规中矩，可以尝试微调饵料。")
        else:
            lines.append("偏低，建议换点或调整钩号。")

        return "".join(lines)

    def generate_fishing_log(self, session_summary_json: str) -> str:
        try:
            stats = json.loads(session_summary_json)
            return self.generate_session_summary(stats)
        except (json.JSONDecodeError, TypeError):
            return "数据解析失败，无法生成日志。"
