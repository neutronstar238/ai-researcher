"""Frozen, outcome-blind source registry for Task 263.4.1.

The registry deliberately separates source inventory from execution.  Task
selection is a deterministic hash ranking over metadata-only candidates; no
OpenML run, score, gold program, prediction, or confirmatory result is queried.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import NamedTuple

from autoresearch.kernel.contracts import canonical_sha256


class ObjectiveTaskFamily(str, Enum):
    """Objective task families admitted to the causal panel."""

    TABULAR_CLASSIFICATION = "tabular_classification"
    TABULAR_REGRESSION = "tabular_regression"


class PanelPartition(str, Enum):
    """Outcome-blind task partitions."""

    DEVELOPMENT = "development"
    CONFIRMATORY = "confirmatory"


class ClassificationCandidate(NamedTuple):
    """One CC18 task with UCI source-license evidence."""

    task_id: int
    data_id: int
    name: str
    source_group: str


class RegressionCandidate(NamedTuple):
    """One CTR23 task and its upstream-declared data license."""

    task_id: int
    data_id: int
    name: str
    source_group: str
    declared_license: str


class FrozenSourceSpec(NamedTuple):
    """Immutable metadata required to identify one selected OpenML task."""

    family: ObjectiveTaskFamily
    benchmark_id: str
    suite_id: int
    task_id: int
    data_id: int
    name: str
    domain: str
    source_group: str
    declared_license: str
    effective_license_id: str
    data_md5: str
    file_id: int


PANEL_SELECTION_SEED = "task-263.4.1-open-objective-panel-v1"
UCI_LICENSE_EVIDENCE_URL = "https://archive.ics.uci.edu/contribute/donation"
OPENML_TERMS_URL = "https://docs.openml.org/intro/terms/"

_OPEN_REGRESSION_LICENSES = frozenset(
    {
        "CC BY 4.0",
        "CC0: Public Domain",
        "CC 0: Public Domain",
        "GPL (>= 2)",
    }
)
_EFFECTIVE_REGRESSION_LICENSES = {
    "CC BY 4.0": "CC-BY-4.0",
    "CC0: Public Domain": "CC0-1.0",
    "CC 0: Public Domain": "CC0-1.0",
    "GPL (>= 2)": "GPL-2.0-or-later",
}


OPENML_CC18_TASK_IDS = (
    3,
    6,
    11,
    12,
    14,
    15,
    16,
    18,
    22,
    23,
    28,
    29,
    31,
    32,
    37,
    43,
    45,
    49,
    53,
    219,
    2074,
    2079,
    3021,
    3022,
    3481,
    3549,
    3560,
    3573,
    3902,
    3903,
    3904,
    3913,
    3917,
    3918,
    7592,
    9910,
    9946,
    9952,
    9957,
    9960,
    9964,
    9971,
    9976,
    9977,
    9978,
    9981,
    9985,
    10093,
    10101,
    14952,
    14954,
    14965,
    14969,
    14970,
    125920,
    125922,
    146195,
    146800,
    146817,
    146819,
    146820,
    146821,
    146822,
    146824,
    146825,
    167119,
    167120,
    167121,
    167124,
    167125,
    167140,
    167141,
)


CLASSIFICATION_CANDIDATES = (
    ClassificationCandidate(3, 3, "kr-vs-kp", "uci-kr-vs-kp"),
    ClassificationCandidate(6, 6, "letter", "uci-letter"),
    ClassificationCandidate(11, 11, "balance-scale", "uci-balance-scale"),
    ClassificationCandidate(12, 12, "mfeat-factors", "uci-multiple-features"),
    ClassificationCandidate(14, 14, "mfeat-fourier", "uci-multiple-features"),
    ClassificationCandidate(15, 15, "breast-w", "uci-breast-w"),
    ClassificationCandidate(16, 16, "mfeat-karhunen", "uci-multiple-features"),
    ClassificationCandidate(18, 18, "mfeat-morphological", "uci-multiple-features"),
    ClassificationCandidate(22, 22, "mfeat-zernike", "uci-multiple-features"),
    ClassificationCandidate(23, 23, "cmc", "uci-cmc"),
    ClassificationCandidate(28, 28, "optdigits", "uci-optdigits"),
    ClassificationCandidate(29, 29, "credit-approval", "uci-credit-approval"),
    ClassificationCandidate(31, 31, "credit-g", "uci-credit-g"),
    ClassificationCandidate(32, 32, "pendigits", "uci-pendigits"),
    ClassificationCandidate(37, 37, "diabetes", "uci-diabetes"),
    ClassificationCandidate(43, 44, "spambase", "uci-spambase"),
    ClassificationCandidate(45, 46, "splice", "uci-splice"),
    ClassificationCandidate(49, 50, "tic-tac-toe", "uci-tic-tac-toe"),
    ClassificationCandidate(53, 54, "vehicle", "uci-vehicle"),
    ClassificationCandidate(2074, 182, "satimage", "uci-satimage"),
    ClassificationCandidate(3021, 38, "sick", "uci-sick"),
    ClassificationCandidate(3022, 307, "vowel", "uci-vowel"),
    ClassificationCandidate(3481, 300, "isolet", "uci-isolet"),
    ClassificationCandidate(7592, 1590, "adult", "uci-adult"),
    ClassificationCandidate(9946, 1510, "wdbc", "uci-wdbc"),
    ClassificationCandidate(9957, 1494, "qsar-biodeg", "uci-qsar-biodeg"),
    ClassificationCandidate(
        9960,
        1497,
        "wall-robot-navigation",
        "uci-wall-robot-navigation",
    ),
    ClassificationCandidate(9964, 1501, "semeion", "uci-semeion"),
    ClassificationCandidate(9971, 1480, "ilpd", "uci-ilpd"),
    ClassificationCandidate(9976, 1485, "madelon", "uci-madelon"),
    ClassificationCandidate(9977, 1486, "nomao", "uci-nomao"),
    ClassificationCandidate(9978, 1487, "ozone-level-8hr", "uci-ozone-level-8hr"),
    ClassificationCandidate(9981, 1468, "cnae-9", "uci-cnae-9"),
    ClassificationCandidate(
        9985,
        1475,
        "first-order-theorem-proving",
        "uci-first-order-theorem-proving",
    ),
    ClassificationCandidate(
        10093,
        1462,
        "banknote-authentication",
        "uci-banknote-authentication",
    ),
    ClassificationCandidate(
        10101,
        1464,
        "blood-transfusion-service-center",
        "uci-blood-transfusion",
    ),
    ClassificationCandidate(
        14952,
        4534,
        "PhishingWebsites",
        "uci-phishing-websites",
    ),
    ClassificationCandidate(14954, 6332, "cylinder-bands", "uci-cylinder-bands"),
    ClassificationCandidate(14965, 1461, "bank-marketing", "uci-bank-marketing"),
    ClassificationCandidate(
        14969,
        4538,
        "GesturePhaseSegmentationProcessed",
        "uci-gesture-phase",
    ),
    ClassificationCandidate(14970, 1478, "har", "uci-har"),
    ClassificationCandidate(125920, 23381, "dresses-sales", "uci-dresses-sales"),
    ClassificationCandidate(146195, 40668, "connect-4", "uci-connect-4"),
    ClassificationCandidate(146800, 40966, "MiceProtein", "uci-mice-protein"),
    ClassificationCandidate(
        146817,
        40982,
        "steel-plates-fault",
        "uci-steel-plates-fault",
    ),
    ClassificationCandidate(
        146819,
        40994,
        "climate-model-simulation-crashes",
        "uci-climate-crashes",
    ),
    ClassificationCandidate(146820, 40983, "wilt", "uci-wilt"),
    ClassificationCandidate(146821, 40975, "car", "uci-car"),
    ClassificationCandidate(146822, 40984, "segment", "uci-segment"),
    ClassificationCandidate(146824, 40979, "mfeat-pixel", "uci-multiple-features"),
    ClassificationCandidate(
        167125,
        40978,
        "Internet-Advertisements",
        "uci-internet-ads",
    ),
    ClassificationCandidate(167140, 40670, "dna", "uci-dna"),
)


REGRESSION_CANDIDATES = (
    RegressionCandidate(361234, 44956, "abalone", "uci-abalone", "CC BY 4.0"),
    RegressionCandidate(
        361235,
        44957,
        "airfoil_self_noise",
        "uci-airfoil-self-noise",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361236,
        44958,
        "auction_verification",
        "uci-auction-verification",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361237,
        44959,
        "concrete_compressive_strength",
        "uci-concrete-strength",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361241,
        44963,
        "physiochemical_protein",
        "uci-protein-tertiary",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361242,
        44964,
        "superconductivity",
        "uci-superconductivity",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361243,
        44965,
        "geographical_origin_of_music",
        "uci-geographical-music",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361244,
        44966,
        "solar_flare",
        "uci-solar-flare",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361247,
        44969,
        "naval_propulsion_plant",
        "uci-naval-propulsion",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361249,
        44971,
        "white_wine",
        "uci-wine-quality",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361250,
        44972,
        "red_wine",
        "uci-wine-quality",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361251,
        44973,
        "grid_stability",
        "uci-grid-stability",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361252,
        44974,
        "video_transcoding",
        "uci-video-transcoding",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361253,
        44975,
        "wave_energy",
        "uci-wave-energy",
        "CC BY 4.0",
    ),
    RegressionCandidate(361254, 44976, "sarcos", "source-sarcos", "Public"),
    RegressionCandidate(
        361255,
        44977,
        "california_housing",
        "source-california-housing",
        "Public",
    ),
    RegressionCandidate(
        361256,
        44978,
        "cpu_activity",
        "source-cpu-activity",
        "Public",
    ),
    RegressionCandidate(361257, 44979, "diamonds", "source-diamonds", "Public"),
    RegressionCandidate(361258, 44980, "kin8nm", "source-kin8nm", "Public"),
    RegressionCandidate(
        361259,
        44981,
        "pumadyn32nh",
        "source-pumadyn32nh",
        "Public",
    ),
    RegressionCandidate(
        361260,
        44983,
        "miami_housing",
        "kaggle-miami-housing",
        "CC0: Public Domain",
    ),
    RegressionCandidate(
        361261,
        44984,
        "cps88wages",
        "source-cps88wages",
        "Public",
    ),
    RegressionCandidate(
        361264,
        44987,
        "socmob",
        "source-socmob",
        "Non-commercial scholarly and teaching purposes.",
    ),
    RegressionCandidate(
        361266,
        44989,
        "kings_county",
        "kaggle-kings-county",
        "CC 0: Public Domain",
    ),
    RegressionCandidate(
        361267,
        44990,
        "brazilian_houses",
        "kaggle-brazilian-houses",
        "CC 0: Public Domain",
    ),
    RegressionCandidate(
        361268,
        44992,
        "fps_benchmark",
        "openml-fps-benchmark",
        "CC BY",
    ),
    RegressionCandidate(
        361269,
        44993,
        "health_insurance",
        "cran-health-insurance",
        "GPL (>= 2)",
    ),
    RegressionCandidate(
        361272,
        45012,
        "fifa",
        "kaggle-fifa",
        "CC0: Public Domain",
    ),
    RegressionCandidate(361616, 41021, "Moneyball", "source-moneyball", "Public"),
    RegressionCandidate(
        361617,
        44960,
        "energy_efficiency",
        "uci-energy-efficiency",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361618,
        44962,
        "forest_fires",
        "uci-forest-fires",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361619,
        44967,
        "student_performance_por",
        "uci-student-performance",
        "CC BY 4.0",
    ),
    RegressionCandidate(
        361621,
        44970,
        "QSAR_fish_toxicity",
        "uci-fish-toxicity",
        "CC BY 4.0",
    ),
    RegressionCandidate(361622, 44994, "cars", "source-cars", "Public"),
    RegressionCandidate(361623, 45402, "space_ga", "source-space-ga", "Public"),
)


_CLASSIFICATION_DOMAINS = {
    3: "games-symbolic",
    6: "vision-signal",
    11: "synthetic-control",
    12: "vision-signal",
    15: "biomedical",
    23: "socioeconomic-health",
    28: "vision-signal",
    31: "socioeconomic-finance",
    32: "vision-signal",
    37: "biomedical",
    43: "text-web",
    45: "biomedical",
    49: "games-symbolic",
    53: "vision-signal",
    2074: "earth-observation",
    3021: "biomedical",
    3022: "audio-speech",
    7592: "socioeconomic",
    9946: "biomedical",
    9957: "environmental-chemistry",
    9960: "robotics",
    9964: "vision-signal",
    9971: "biomedical",
    9976: "synthetic-algorithmic",
    9977: "web-entity-resolution",
    9978: "earth-environment",
    9981: "text-web",
    9985: "symbolic-reasoning",
    10093: "forensics",
    10101: "biomedical",
    14952: "cybersecurity-web",
    14954: "manufacturing",
    14965: "socioeconomic-finance",
    14969: "sensor-signal",
    14970: "sensor-signal",
    125920: "retail",
    146195: "games-symbolic",
    146800: "biomedical",
    146817: "manufacturing",
    146819: "earth-environment",
    146820: "agriculture",
    146821: "decision-systems",
    146822: "vision-signal",
    167125: "text-web",
    167140: "biomedical",
}

_REGRESSION_DOMAINS = {
    361234: "biology",
    361235: "engineering",
    361236: "market-simulation",
    361237: "materials",
    361241: "biology",
    361242: "materials",
    361243: "audio-music",
    361244: "space-weather",
    361247: "engineering",
    361250: "food-chemistry",
    361251: "energy",
    361252: "computing",
    361253: "energy",
    361260: "housing",
    361266: "housing",
    361267: "housing",
    361269: "health-economics",
    361272: "sports",
    361617: "energy",
    361618: "earth-environment",
    361619: "education",
    361621: "environmental-chemistry",
}


# task_id, data_id, name, md5, file_id
_CLASSIFICATION_METADATA = (
    (3, 3, "kr-vs-kp", "ad6eb32b7492524d4382a40e23cdbb8e", 3),
    (6, 6, "letter", "9d8a79dccd72f429b67b88387e994db8", 6),
    (11, 11, "balance-scale", "76938608d472f620c170cef9c8c1fa65", 11),
    (12, 12, "mfeat-factors", "2c55b6bb1ad6eaad86d6e6bc0a1d4e1b", 12),
    (15, 15, "breast-w", "88633c065209e7a57323d3d7f2d00546", 52350),
    (23, 23, "cmc", "3149646ecff276abac3e892d1556655f", 23),
    (28, 28, "optdigits", "d9d357ab8cfb6732853109e472d9cfce", 28),
    (31, 31, "credit-g", "9a475053fed0c26ee95cd4525e50074c", 31),
    (32, 32, "pendigits", "6e472ab352f3f62cc4087dc78eda8d3d", 32),
    (37, 37, "diabetes", "3cbaa3e54586aa88cf6aacb4033e4470", 37),
    (43, 44, "spambase", "d9ace01aeac3461e326a8e1b2d53fd84", 44),
    (45, 46, "splice", "21a60c8d1b14bbf0f146b4afeda39287", 46),
    (49, 50, "tic-tac-toe", "34b2992c41e5e23c42769817e96305ac", 50),
    (53, 54, "vehicle", "fbba18157b188f309d772f9ca4e578f5", 54),
    (2074, 182, "satimage", "72857195d1f6c4c2171c386594f870b2", 3619),
    (3021, 38, "sick", "ee5cb4b7f41a5f44b0cd234f675ab492", 38),
    (3022, 307, "vowel", "9c82432df30166fc62353fe4f8bb237a", 52210),
    (7592, 1590, "adult", "bb6510925e5d4b23d136715febb2cdf5", 1595261),
    (9946, 1510, "wdbc", "7aa183d3657e364911ced0cbd6b272bd", 1592318),
    (9957, 1494, "qsar-biodeg", "a2c189cd65511103fa540d7186155c24", 1592286),
    (
        9960,
        1497,
        "wall-robot-navigation",
        "05d4fd7921f662a911dc41eafb5a5183",
        1592289,
    ),
    (9964, 1501, "semeion", "0fb35a1d7db2f76c8587f9125abcf048", 1592293),
    (9971, 1480, "ilpd", "155295549a459387fb71312caf1b8360", 1590565),
    (9976, 1485, "madelon", "9a4a0c7fa94e6f824962b4c6fbd1812c", 1590986),
    (9977, 1486, "nomao", "8fc1ac73fbe5236892e166f9f24d7221", 1592278),
    (
        9978,
        1487,
        "ozone-level-8hr",
        "6e6b7aeb382e30ae79149e4e5845cf2d",
        1592279,
    ),
    (9981, 1468, "cnae-9", "76e93d20cebbeb462d01358a94a464e2", 1586233),
    (
        9985,
        1475,
        "first-order-theorem-proving",
        "18085f8fa7a64f3870327ae4d9ff4123",
        1587932,
    ),
    (
        10093,
        1462,
        "banknote-authentication",
        "baa2dc5b745775a943ebeb9c276401f8",
        1586223,
    ),
    (
        10101,
        1464,
        "blood-transfusion-service-center",
        "c3242468edab8c2e7a907674122dc851",
        1586225,
    ),
    (
        14952,
        4534,
        "PhishingWebsites",
        "fa52215c3e8caba4b765afa33bc92657",
        1798106,
    ),
    (
        14954,
        6332,
        "cylinder-bands",
        "59ec3d17d1fb9fa79c3108a7a5a9bc5e",
        1854224,
    ),
    (
        14965,
        1461,
        "bank-marketing",
        "b29d2eb78e508569fd41172c97bda00e",
        1586218,
    ),
    (
        14969,
        4538,
        "GesturePhaseSegmentationProcessed",
        "31a6e4f8cdae2b8141c1f754e0366007",
        1798765,
    ),
    (14970, 1478, "har", "7b1e71116a88aa1d88b43e697f7c67ee", 1589271),
    (
        125920,
        23381,
        "dresses-sales",
        "996f7aacb2eab289cc1a968e263f5281",
        1910507,
    ),
    (
        146195,
        40668,
        "connect-4",
        "1e84a44f5994bc14039544917cca265e",
        4965243,
    ),
    (
        146800,
        40966,
        "MiceProtein",
        "3c479a6885bfa0438971388283a1ce32",
        17928620,
    ),
    (
        146817,
        40982,
        "steel-plates-fault",
        "7ccdabeb01749cce9fa3b1d4a702fb8c",
        18151921,
    ),
    (
        146819,
        40994,
        "climate-model-simulation-crashes",
        "f7c55d9a11782a5ff980cee371787edd",
        18237248,
    ),
    (146820, 40983, "wilt", "aa7c0aaf3fd671f06bbf6a68be4754f7", 18151926),
    (146821, 40975, "car", "baf70f94f550c2ba489422bb742c54ae", 18116966),
    (
        146822,
        40984,
        "segment",
        "dc39e654f66a5a4007012e74ef3f1435",
        18151937,
    ),
    (
        167125,
        40978,
        "Internet-Advertisements",
        "4f8829d20c886c86de4bc06c4eeb5cc6",
        18140371,
    ),
    (167140, 40670, "dna", "b17662de56a4f897f9b89514ebf56aa8", 4965245),
)

_REGRESSION_METADATA = (
    (361234, 44956, "abalone", "81f6d8b4dce14710077ab88389254d83", 22111820),
    (
        361235,
        44957,
        "airfoil_self_noise",
        "60e512ce65710079292e99a3acc71886",
        22111821,
    ),
    (
        361236,
        44958,
        "auction_verification",
        "fee9a1bd5d59943c9a83508a401821c8",
        22111822,
    ),
    (
        361237,
        44959,
        "concrete_compressive_strength",
        "1906eae71bd8b8142d079a4b966549ac",
        22111823,
    ),
    (
        361241,
        44963,
        "physiochemical_protein",
        "a7e9bb5d3d78ac0c5aad3edcb26404b0",
        22111827,
    ),
    (
        361242,
        44964,
        "superconductivity",
        "14f13f8994cf3e2fb32a667e0818a522",
        22111828,
    ),
    (
        361243,
        44965,
        "geographical_origin_of_music",
        "a5a6222b5b79a8a0bb441667766d41b0",
        22111829,
    ),
    (
        361244,
        44966,
        "solar_flare",
        "f8b0a7c961d3329e1bcea52c724bd724",
        22111830,
    ),
    (
        361247,
        44969,
        "naval_propulsion_plant",
        "27484a3481ad60205656f6b6b191996b",
        22111833,
    ),
    (
        361250,
        44972,
        "red_wine",
        "710b6653907aba6b655fd4a59fba71eb",
        22111836,
    ),
    (
        361251,
        44973,
        "grid_stability",
        "00e8b2c1d077474945d1604a6196c496",
        22111837,
    ),
    (
        361252,
        44974,
        "video_transcoding",
        "5ea7f591ea55b489e7057a523ce42a61",
        22111838,
    ),
    (
        361253,
        44975,
        "wave_energy",
        "762a4638b1019db2db361d1c018e3e92",
        22111839,
    ),
    (
        361260,
        44983,
        "miami_housing",
        "7a89f2ba4aa504d0df53b49b3204f426",
        22111847,
    ),
    (
        361266,
        44989,
        "kings_county",
        "3cb78791be3a56d76c7860e2812d3185",
        22111853,
    ),
    (
        361267,
        44990,
        "brazilian_houses",
        "4035c290a9c383fbc7aa3dde90b11e40",
        22111854,
    ),
    (
        361269,
        44993,
        "health_insurance",
        "6c3993159d394af13ed909285a3927fa",
        22111857,
    ),
    (361272, 45012, "fifa", "ed275765771323948ebe41edea924016", 22111894),
    (
        361617,
        44960,
        "energy_efficiency",
        "9e361531fc8e672174ddb393144a60c9",
        22111824,
    ),
    (
        361618,
        44962,
        "forest_fires",
        "0de257b0ce71eb197e1c774a4071705b",
        22111826,
    ),
    (
        361619,
        44967,
        "student_performance_por",
        "cee70f2a16e9c52694bf0bb77603b4e8",
        22111831,
    ),
    (
        361621,
        44970,
        "QSAR_fish_toxicity",
        "4900e250afcfee9d523aba87895260fe",
        22111834,
    ),
)


def _selection_rank(label: str) -> str:
    return hashlib.sha256(f"{PANEL_SELECTION_SEED}:{label}".encode()).hexdigest()


def _deduplicated_classification_candidates() -> list[ClassificationCandidate]:
    groups: dict[str, list[ClassificationCandidate]] = {}
    for candidate in CLASSIFICATION_CANDIDATES:
        groups.setdefault(candidate.source_group, []).append(candidate)
    representatives = [
        min(
            members,
            key=lambda item: _selection_rank(f"classification-member:{item.task_id}"),
        )
        for members in groups.values()
    ]
    return sorted(
        representatives,
        key=lambda item: _selection_rank(f"classification-unit:{item.task_id}"),
    )


def _deduplicated_regression_candidates() -> list[RegressionCandidate]:
    groups: dict[str, list[RegressionCandidate]] = {}
    for candidate in REGRESSION_CANDIDATES:
        if candidate.declared_license not in _OPEN_REGRESSION_LICENSES:
            continue
        groups.setdefault(candidate.source_group, []).append(candidate)
    representatives = [
        min(
            members,
            key=lambda item: _selection_rank(f"regression-member:{item.task_id}"),
        )
        for members in groups.values()
    ]
    return sorted(
        representatives,
        key=lambda item: _selection_rank(f"regression-unit:{item.task_id}"),
    )


def frozen_panel_partitions() -> dict[tuple[ObjectiveTaskFamily, int], PanelPartition]:
    """Return the metadata-only, prospectively ranked panel assignment."""

    classification = _deduplicated_classification_candidates()[:45]
    regression = _deduplicated_regression_candidates()
    if len(classification) != 45 or len(regression) != 22:
        raise RuntimeError("frozen task inventory no longer has the expected size")

    assignments: dict[tuple[ObjectiveTaskFamily, int], PanelPartition] = {}
    for index, classification_candidate in enumerate(classification):
        assignments[
            (
                ObjectiveTaskFamily.TABULAR_CLASSIFICATION,
                classification_candidate.task_id,
            )
        ] = (
            PanelPartition.DEVELOPMENT if index < 4 else PanelPartition.CONFIRMATORY
        )
    for index, regression_candidate in enumerate(regression):
        assignments[
            (
                ObjectiveTaskFamily.TABULAR_REGRESSION,
                regression_candidate.task_id,
            )
        ] = (
            PanelPartition.DEVELOPMENT if index < 3 else PanelPartition.CONFIRMATORY
        )
    return assignments


def frozen_selection_exclusions() -> dict[str, str]:
    """Return every source-suite exclusion with a non-outcome reason."""

    exclusions: dict[str, str] = {}
    classification_representatives = _deduplicated_classification_candidates()
    selected_classification = {item.task_id for item in classification_representatives[:45]}
    representative_ids = {item.task_id for item in classification_representatives}
    candidate_ids = {item.task_id for item in CLASSIFICATION_CANDIDATES}
    for task_id in OPENML_CC18_TASK_IDS:
        key = f"openml-cc18:{task_id}"
        if task_id not in candidate_ids:
            exclusions[key] = "no-source-specific-open-license-evidence"
        elif task_id not in representative_ids:
            exclusions[key] = "non-independent-source-duplicate"
        elif task_id not in selected_classification:
            exclusions[key] = "prospective-capacity-rank-excluded"

    selected_regression = {item.task_id for item in _deduplicated_regression_candidates()}
    for item in REGRESSION_CANDIDATES:
        key = f"openml-ctr23:{item.task_id}"
        if item.task_id in selected_regression:
            continue
        if item.declared_license == "Public":
            exclusions[key] = "ambiguous-public-license-label"
        elif item.declared_license == "CC BY":
            exclusions[key] = "license-version-unspecified"
        elif item.declared_license.startswith("Non-commercial"):
            exclusions[key] = "non-open-noncommercial-license"
        else:
            exclusions[key] = "non-independent-source-duplicate"
    return dict(sorted(exclusions.items()))


def frozen_sources() -> tuple[FrozenSourceSpec, ...]:
    """Return and internally audit the selected immutable source metadata."""

    classification_lookup = {item.task_id: item for item in CLASSIFICATION_CANDIDATES}
    regression_lookup = {item.task_id: item for item in REGRESSION_CANDIDATES}
    sources: list[FrozenSourceSpec] = []
    for task_id, data_id, name, data_md5, file_id in _CLASSIFICATION_METADATA:
        classification_candidate = classification_lookup[task_id]
        sources.append(
            FrozenSourceSpec(
                ObjectiveTaskFamily.TABULAR_CLASSIFICATION,
                "openml-cc18",
                99,
                task_id,
                data_id,
                name,
                _CLASSIFICATION_DOMAINS[task_id],
                classification_candidate.source_group,
                "Public",
                "CC-BY-4.0",
                data_md5,
                file_id,
            )
        )
    for task_id, data_id, name, data_md5, file_id in _REGRESSION_METADATA:
        regression_candidate = regression_lookup[task_id]
        sources.append(
            FrozenSourceSpec(
                ObjectiveTaskFamily.TABULAR_REGRESSION,
                "openml-ctr23",
                353,
                task_id,
                data_id,
                name,
                _REGRESSION_DOMAINS[task_id],
                regression_candidate.source_group,
                regression_candidate.declared_license,
                _EFFECTIVE_REGRESSION_LICENSES[regression_candidate.declared_license],
                data_md5,
                file_id,
            )
        )

    assignments = frozen_panel_partitions()
    actual_keys = {(source.family, source.task_id) for source in sources}
    if actual_keys != set(assignments):
        raise RuntimeError("frozen source metadata does not match panel assignment")
    if len({source.data_id for source in sources}) != len(sources):
        raise RuntimeError("frozen task panel repeats an OpenML dataset")
    if len({source.source_group for source in sources}) != len(sources):
        raise RuntimeError("frozen task panel repeats an independence group")
    return tuple(sorted(sources, key=lambda item: (item.family.value, item.task_id)))


def frozen_source_registry_hash() -> str:
    """Return the canonical digest of source metadata, splits, and exclusions."""

    assignments = frozen_panel_partitions()
    payload = {
        "selection_seed": PANEL_SELECTION_SEED,
        "sources": [
            {
                **source._asdict(),
                "family": source.family.value,
                "partition": assignments[(source.family, source.task_id)].value,
            }
            for source in frozen_sources()
        ],
        "exclusions": frozen_selection_exclusions(),
    }
    return canonical_sha256(payload)
