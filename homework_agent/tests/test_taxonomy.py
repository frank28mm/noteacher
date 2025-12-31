from homework_agent.utils.taxonomy import normalize_knowledge_tags, taxonomy_version


def test_taxonomy_version_present():
    assert taxonomy_version()


def test_normalize_knowledge_tags_applies_aliases_and_dedupes():
    tags = ["勾股定理", "毕达哥拉斯定理", " ", "勾股定理"]
    out = normalize_knowledge_tags(tags)
    assert out == ["勾股定理"]

