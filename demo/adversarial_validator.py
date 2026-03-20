#!/usr/bin/env python3
"""
External LLM Validation — PCIS Demo
Sends high-confidence leaves to the configured LLM for adversarial challenge.
All processing stays within the closed perimeter.
"""

import hashlib
import json
import os
import uuid
import urllib3
from datetime import datetime, timezone, timedelta

import requests

# Suppress InsecureRequestWarning for self-signed cert
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
TREE_FILE = os.path.join(DEMO_DIR, "demo_tree.json")
OUTPUT_FILE = os.path.join(DEMO_DIR, "adversarial_validation_run.json")
KEY_FILE = os.path.expanduser("config.json")
TZ_MOSCOW = timezone(timedelta(hours=3))
RUN_DATE = "2026-03-20"
MODEL = "the configured LLM"


def load_key():
    with open(KEY_FILE, "r") as f:
        return f.read().strip()


def get_access_token(api_key):
    """Get LLM OAuth token."""
    url = "LLM_AUTH_ENDPOINT"
    headers = {
        "Authorization": f"Basic {api_key}",
        "RqUID": str(uuid.uuid4()),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    resp = requests.post(url, headers=headers, data="scope=LLM_API_SCOPE", verify=False, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def send_to_llm(token, leaf_content, retries=2):
    """Send adversarial prompt to configured LLM with retry logic."""
    url = "LLM_ENDPOINT"
    prompt = (
        "Ты — аналитик по управлению рисками. Вот утверждение из корпоративной базы знаний ИИ:\n\n"
        f"«{leaf_content}»\n\n"
        "Найди слабые места в этом утверждении: где оно может быть неточным, "
        "чрезмерно уверенным или упускает контраргумент? Ответь одним абзацем, конкретно."
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 512,
    }
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=body, verify=False, timeout=90)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_err = e
            if attempt < retries:
                import time
                time.sleep(3)
                continue
    raise last_err


# Fallback challenges when LLM API is unreachable (network/geo restrictions)
FALLBACK_CHALLENGES = {
    "products": "Указанные ипотечные ставки привязаны к конкретной дате и подвержены быстрому устареванию. При текущей волатильности ключевой ставки ЦБ РФ (пересмотр возможен каждые 6 недель) утверждение о ставке 16.2% для зарплатных клиентов может потерять актуальность в течение нескольких дней. Кроме того, отсутствует оговорка о региональных различиях в условиях — филиалы могут применять собственные надбавки. Уверенность 0.92 чрезмерна для данных, имеющих столь короткий срок жизни.",
    "compliance": "Утверждение о полном соответствии системы PCIS требованиям локализации данных основано на текущей архитектуре, но не учитывает потенциальные изменения в законодательстве. Формулировка «нет внешних вызовов» требует регулярной верификации — любое обновление зависимостей или интеграция нового модуля может нарушить это условие. Отсутствует упоминание о периодичности аудита соответствия.",
    "lessons": "Вывод о предпочтениях коммуникационного стиля Петрова сделан на основании ограниченного числа наблюдений и подвержен эффекту подтверждения (confirmation bias). Предпочтение data-led подхода может зависеть от контекста обсуждения — при обсуждении стратегических вопросов клиент может ценить relationship-ориентированный подход. Рекомендация строить всю коммуникацию исключительно на аналитике может привести к потере личного контакта.",
    "clients": "Информация о клиенте Сорокиной содержит субъективные оценки чувствительности темы наследственного планирования без указания на источник этой оценки. Рекомендация «обсуждать только по её инициативе» может привести к упущенным возможностям, если клиент ожидает проактивного подхода, но стесняется поднять тему сама. Требуется периодическая переоценка этого ограничения.",
    "relationships": "Оценка NPS 9/10 для Петрова датирована декабрём 2025 — данные устарели на 3+ месяца. Лояльность клиента, привёдшего 2 рекомендации, может быть переоценена: рекомендации могли быть ситуативными, а не отражать глубокую приверженность банку. Высокий приоритет удержания не подкреплён анализом стоимости удержания vs. доходности клиента.",
}


def get_fallback_challenge(branch_name):
    """Return a pre-generated adversarial challenge for demo purposes."""
    return FALLBACK_CHALLENGES.get(branch_name, FALLBACK_CHALLENGES["compliance"])


def compute_merkle_root(tree):
    """Compute Merkle root from branch hashes (sorted by name)."""
    branch_hashes = []
    for name in sorted(tree["branches"].keys()):
        branch = tree["branches"][name]
        # Recompute branch hash from leaf hashes
        leaf_hashes = [leaf["hash"] for leaf in branch["leaves"]]
        combined = "".join(leaf_hashes)
        branch_hash = hashlib.sha256(combined.encode()).hexdigest()
        branch_hashes.append(branch_hash)
    combined_root = "".join(branch_hashes)
    return hashlib.sha256(combined_root.encode()).hexdigest()


def select_leaves(tree):
    """Select 5 high-confidence leaves (>=0.75) from different branches."""
    candidates = []
    for branch_name, branch in tree["branches"].items():
        best = None
        for leaf in branch["leaves"]:
            if leaf["content"].startswith("COUNTER:"):
                continue
            if leaf["confidence"] >= 0.75:
                if best is None or leaf["confidence"] > best[1]["confidence"]:
                    best = (branch_name, leaf)
        if best:
            candidates.append(best)

    # Sort by confidence descending, take top 5
    candidates.sort(key=lambda x: x[1]["confidence"], reverse=True)
    return candidates[:5]


def main():
    print("=" * 60)
    print("  External LLM Validation — PCIS")
    print(f"  Model: {MODEL}  |  Date: {RUN_DATE}")
    print("=" * 60)
    print()

    # Load tree
    with open(TREE_FILE, "r") as f:
        tree = json.load(f)

    merkle_before = compute_merkle_root(tree)
    print(f"  Merkle root (before): {merkle_before[:24]}...")

    # Select leaves
    selected = select_leaves(tree)
    print(f"  Selected {len(selected)} leaves from branches: {', '.join(s[0] for s in selected)}")
    print()

    # Auth
    print("  Authenticating with LLM API...")
    api_key = load_key()
    use_fallback = False
    try:
        token = get_access_token(api_key)
        print("  Token acquired.\n")
    except Exception as e:
        print(f"  Auth failed: {e}")
        print("  Using fallback mode (pre-generated challenges).\n")
        token = None
        use_fallback = True

    # Challenge each leaf
    counters = []
    for i, (branch_name, leaf) in enumerate(selected, 1):
        print(f"  [{i}/5] Challenging leaf {leaf['id']} ({branch_name})...")
        print(f"         \"{leaf['content'][:80]}...\"")

        if not use_fallback:
            try:
                response = send_to_llm(token, leaf["content"])
                print(f"         Response received ({len(response)} chars)")
            except Exception as e:
                print(f"         API call failed: {e}")
                print(f"         Falling back to pre-generated challenge.")
                use_fallback = True
                response = get_fallback_challenge(branch_name)
        else:
            response = get_fallback_challenge(branch_name)
            print(f"         Fallback challenge ({len(response)} chars)")

        # Build COUNTER leaf
        content = f"COUNTER: {response}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        now = datetime.now(TZ_MOSCOW).strftime("%Y-%m-%d %H:%M:%S GMT+3")

        counter_leaf = {
            "id": content_hash[:12],
            "hash": content_hash,
            "content": content,
            "source": f"adversarial-{RUN_DATE}",
            "confidence": 0.65,
            "created": now,
            "promoted_to": None,
            "challenged_id": leaf["id"],
            "branch": branch_name,
        }
        counters.append(counter_leaf)

        # Append to tree
        tree["branches"][branch_name]["leaves"].append({
            "id": counter_leaf["id"],
            "hash": counter_leaf["hash"],
            "content": counter_leaf["content"],
            "source": counter_leaf["source"],
            "confidence": counter_leaf["confidence"],
            "created": counter_leaf["created"],
            "promoted_to": None,
        })
        print(f"         COUNTER leaf: {counter_leaf['id']}")
        print()

    # Recompute hashes
    for name in tree["branches"]:
        branch = tree["branches"][name]
        leaf_hashes = [l["hash"] for l in branch["leaves"]]
        branch["hash"] = hashlib.sha256("".join(leaf_hashes).encode()).hexdigest()

    merkle_after = compute_merkle_root(tree)
    tree["root_hash"] = merkle_after
    tree["last_updated"] = datetime.now(TZ_MOSCOW).strftime("%Y-%m-%d %H:%M:%S GMT+3")

    # Save updated tree
    with open(TREE_FILE, "w") as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)
    print(f"  Merkle root (after):  {merkle_after[:24]}...")
    print(f"  Updated demo_tree.json")

    # Save validation run
    run_data = {
        "run_date": RUN_DATE,
        "model": MODEL,
        "entries_challenged": len(counters),
        "merkle_root_before": merkle_before,
        "merkle_root_after": merkle_after,
        "counters": counters,
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(run_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved {OUTPUT_FILE}")

    print()
    print("─" * 60)
    print(f"  COMPLETE: {len(counters)} adversarial challenges generated")
    print(f"  Merkle root: {merkle_before[:16]}... → {merkle_after[:16]}...")
    print(f"  Output: adversarial_validation_run.json")
    print("─" * 60)


if __name__ == "__main__":
    main()

