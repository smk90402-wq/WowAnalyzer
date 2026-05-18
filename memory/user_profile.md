---
name: user profile
description: User's language, interests, and technical context
type: user
---

- Communicates in Korean — respond in Korean by default
- WoW player, familiar with raid/log/spec terminology (uses Korean WoW jargon like "네임드", "한밤" for Midnight expansion, "외부 버프 제외")
- Python is installed locally
- API credentials (WCL V2 client_id/secret, Blizzard client_id/secret): user **explicitly chose not to rotate** even after chat exposure — they reuse the same credentials across multiple working environments. Do NOT remind them to rotate anymore. Still enforce `.env` / `keys_local.txt` stay gitignored so the secrets don't get committed.
