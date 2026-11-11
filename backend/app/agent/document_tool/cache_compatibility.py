"""Exact source versions whose completed, masked documents remain compatible.

Only reviewed implementation changes belong here. A later source edit stops
matching automatically; model, privacy, safety and OCR settings still must match.
"""

COMPATIBLE_SOURCE_DIGESTS: dict[tuple[str, str], tuple[str, str]] = {
    # Bounded page OCR concurrency; prompts and masking rules are unchanged.
    ("587ac8999e254630b105632ad21388a8fddb929f9b2bd645470afadd5d467d86",
     "13e9786e79f994520a8fa5c2c61f754a77ffdf20bf2eff8d4973639936abcf43"):
    ("513d86b131c3915b48bea60bbdd955b6026219a119d8c4613396289880fbc5fa",
     "13e9786e79f994520a8fa5c2c61f754a77ffdf20bf2eff8d4973639936abcf43"),
}
