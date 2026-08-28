# Recommended analyzer preset: rules + quote truth first; RAG + cross-encoders curate context;
# LLMs structure extraction/commentary (not DETERMINISTIC_CONTRACT_MODE).
#
# Usage (from repo root, after or instead of sourcing env_day_to_day.sh):
#   source scripts/env_structured_analyzer.sh
#
export ANALYZER_PRESET="${ANALYZER_PRESET:-structured}"
export CROSS_ENCODER_DEVICE="${CROSS_ENCODER_DEVICE:-cpu}"
