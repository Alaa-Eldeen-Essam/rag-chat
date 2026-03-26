import re
from typing import Dict, List, Set


def _tokenize(text: str, min_token_len: int = 4) -> List[str]:
    if not text:
        return []
    tokens = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
    return [tok for tok in tokens if len(tok) >= min_token_len]


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"[\.!\?؟\n]+", text)
    return [part.strip() for part in parts if part and part.strip()]


def _best_claim_overlap(claim: str, evidence_sentences: List[Set[str]], min_token_len: int) -> float:
    claim_tokens = set(_tokenize(claim, min_token_len=min_token_len))
    if not claim_tokens:
        return 1.0
    best = 0.0
    for sent_tokens in evidence_sentences:
        if not sent_tokens:
            continue
        overlap = len(claim_tokens.intersection(sent_tokens)) / max(1, len(claim_tokens))
        if overlap > best:
            best = overlap
            if best >= 1.0:
                break
    return best


def grounding_report(
    answer: str,
    evidence_corpus: str,
    *,
    min_token_len: int = 4,
    min_token_matches: int = 2,
    min_claim_overlap: float = 0.20,
    max_ungrounded_claims: int = 1,
    max_claims: int = 6,
) -> Dict[str, object]:
    if not answer:
        return {
            "grounded": False,
            "lexical_matches": 0,
            "claims_checked": 0,
            "ungrounded_claims": 0,
            "grounded_claims": 0,
            "grounded_claim_ratio": 0.0,
            "best_overlap_avg": 0.0,
            "claim_overlaps": [],
        }

    evidence_tokens = set(_tokenize(evidence_corpus or "", min_token_len=min_token_len))
    answer_tokens = list(dict.fromkeys(_tokenize(answer, min_token_len=min_token_len)))
    lexical_matches = sum(1 for tok in answer_tokens if tok in evidence_tokens)
    lexical_ok = lexical_matches >= max(1, min_token_matches)

    evidence_sentence_tokens = [
        set(_tokenize(sentence, min_token_len=min_token_len))
        for sentence in _split_sentences(evidence_corpus or "")
    ]
    claims = _split_sentences(answer)[:max_claims]

    overlaps: List[float] = []
    ungrounded = 0
    grounded_claims = 0
    for claim in claims:
        overlap = _best_claim_overlap(
            claim,
            evidence_sentence_tokens,
            min_token_len=min_token_len,
        )
        overlaps.append(overlap)
        if overlap < min_claim_overlap:
            ungrounded += 1
        else:
            grounded_claims += 1

    claims_ok = ungrounded <= max(0, int(max_ungrounded_claims))
    grounded = bool(lexical_ok and claims_ok)
    avg_overlap = (sum(overlaps) / len(overlaps)) if overlaps else 1.0
    grounded_claim_ratio = (
        float(grounded_claims) / float(len(claims))
        if claims
        else 1.0
    )
    return {
        "grounded": grounded,
        "lexical_matches": lexical_matches,
        "claims_checked": len(claims),
        "ungrounded_claims": ungrounded,
        "grounded_claims": grounded_claims,
        "grounded_claim_ratio": grounded_claim_ratio,
        "best_overlap_avg": avg_overlap,
        "claim_overlaps": overlaps,
    }
