from evidence_retrieval import bm25_scores, evidence_excerpt, fuse_candidate_ranks, lexical_tokens


def test_chinese_bigrams_and_identifiers_are_preserved():
    assert lexical_tokens('缺陷处置 TS-999 env_file') == ['缺陷', '陷处', '处置', 'ts-999', 'env_file']


def test_bm25_rewards_specific_short_evidence_without_raw_source_weights():
    scores = bm25_scores(['generic report', 'TS-999 resolved', 'TS-999 ' + 'other ' * 500], 'TS-999')
    assert scores[1] > scores[2] > scores[0]


def test_fusion_can_surface_precise_chat_above_less_focused_material():
    rows = [
        {'source_name': 'report', 'snippet': 'TS-999 ' + 'background ' * 500, 'score': 150},
        {'source_name': 'authorized chat', 'snippet': 'TS-999 fixed', 'score': 55},
    ]
    results = fuse_candidate_ranks(rows, 'TS-999')
    assert results[0]['source_name'] == 'authorized chat'
    assert results[0]['lexical_score'] > results[1]['lexical_score']


def test_excerpt_includes_late_literal_hit_and_keeps_source_case():
    text = '背景' * 600 + 'TS-999 已解决' + '后续' * 600
    excerpt = evidence_excerpt(text, 'ts-999')
    assert 'TS-999 已解决' in excerpt
    assert len(excerpt) <= 502
    assert excerpt.startswith('…') and excerpt.endswith('…')


def test_symbol_only_ranking_preserves_literal_order():
    rows = [{'source_name': 'first', 'snippet': '50%'}, {'source_name': 'second', 'snippet': '%'}]
    assert fuse_candidate_ranks(rows, '%') == rows
