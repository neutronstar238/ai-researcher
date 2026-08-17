"""文献源共用的解析/领域判断工具（纯函数，便于单测）。"""

from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")

# 医药/生物相关关键词（启发式）：PubMed 仅对医药相关问题生效（用户约束）。
# 命中任意一个即视为医药问题；小写后子串匹配。
_MEDICAL_KEYWORDS: frozenset[str] = frozenset(
    {
        # 英文
        "disease", "disorder", "syndrome", "cancer", "tumor", "tumour", "carcinoma",
        "oncology", "leukemia", "melanoma", "drug", "pharmac", "pharma", "medicine",
        "medical", "clinical", "patient", "therapy", "therapeutic", "treatment",
        "diagnosis", "diagnostic", "prognosis", "biomarker", "vaccine", "immun",
        "virus", "viral", "bacteria", "bacterial", "infection", "infectious",
        "antibiotic", "antibody", "antigen", "inflammation", "inflammatory",
        "protein", "gene", "genome", "genetic", "mutation", "molecular", "cell",
        "cellular", "tissue", "organ", "physiolog", "patholog", "anatomy", "brain",
        "neuron", "neural", "cardiac", "cardiovascular", "pulmonary", "renal",
        "hepatic", "liver", "lung", "heart", "diabetes", "obesity", "hypertension",
        "alzheimer", "parkinson", "depression", "anxiety", "schizophrenia",
        "metabolism", "metabolic", "enzyme", "receptor", "ligand", "binding affinity",
        "dose", "trial", "cohort", "epidemiolog", "surgery", "surgical", "anesthesia",
        "pediatric", "geriatric", "nursing", "dental", "ophthalm", "dermatolog",
        "neurolog", "psychiatr", "oncol", "hematolog", "rheumat", "endocrin",
        "nephrolog", "gastroenter", "urolog", "gynecolog", "obstetric",
        # 中文
        "疾病", "癌症", "肿瘤", "药", "医", "临床", "患者", "治疗", "诊断", "疫苗",
        "病毒", "细菌", "感染", "免疫", "蛋白", "基因", "细胞", "器官", "心脏",
        "肝脏", "肺", "糖尿病", "高血压", "抑郁", "手术", "儿科",
    }
)


def strip_tags(text: str) -> str:
    """去掉 XML/HTML 标签并规整空白（用于 Crossref/PubMed 的富文本摘要）。"""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", text)).strip()


def reconstruct_inverted_index(inverted: dict | None) -> str:
    """OpenAlex 的 `abstract_inverted_index` → 原文摘要。"""
    if not inverted:
        return ""
    position_to_word: dict[int, str] = {}
    for word, positions in inverted.items():
        for pos in positions:
            position_to_word[pos] = word
    return " ".join(position_to_word[i] for i in sorted(position_to_word))


def is_medical_query(text: str) -> bool:
    """启发式判断是否为医药相关问题（PubMed 领域门控）。"""
    lowered = text.lower()
    return any(keyword in lowered for keyword in _MEDICAL_KEYWORDS)
