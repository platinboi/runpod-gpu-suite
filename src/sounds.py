"""
Static TikTok sounds list - hardcoded to avoid database dependency on RunPod.
"""
import random
from typing import Dict, List

TIKTOK_SOUNDS = [
    {"name": "abx_617750", "url": "https://storage.nocodecult.io/sounds/abx_617750.mp3"},
    {"name": "aryan_405142", "url": "https://storage.nocodecult.io/sounds/aryan_405142.mp3"},
    {"name": "audge_436110", "url": "https://storage.nocodecult.io/sounds/audge_436110.mp3"},
    {"name": "byebye_301713", "url": "https://storage.nocodecult.io/sounds/byebye_301713.mp3"},
    {"name": "cam_982175", "url": "https://storage.nocodecult.io/sounds/cam_982175.mp3"},
    {"name": "ceezy_024278", "url": "https://storage.nocodecult.io/sounds/ceezy_024278.mp3"},
    {"name": "choso_373014", "url": "https://storage.nocodecult.io/sounds/choso_373014.mp3"},
    {"name": "dream_036374", "url": "https://storage.nocodecult.io/sounds/dream_036374.mp3"},
    {"name": "fever_407568", "url": "https://storage.nocodecult.io/sounds/fever_407568.mp3"},
    {"name": "fithackers_370326", "url": "https://storage.nocodecult.io/sounds/fithackers_370326.mp3"},
    {"name": "flop_102038", "url": "https://storage.nocodecult.io/sounds/flop_102038.mp3"},
    {"name": "hamster_994401", "url": "https://storage.nocodecult.io/sounds/hamster_994401.mp3"},
    {"name": "hardtekk_594897", "url": "https://storage.nocodecult.io/sounds/hardtekk_594897.mp3"},
    {"name": "havanagila_799377", "url": "https://storage.nocodecult.io/sounds/havanagila_799377.mp3"},
    {"name": "jacob_570782", "url": "https://storage.nocodecult.io/sounds/jacob_570782.mp3"},
    {"name": "lost_353271", "url": "https://storage.nocodecult.io/sounds/lost_353271.mp3"},
    {"name": "ltb_458015", "url": "https://storage.nocodecult.io/sounds/ltb_458015.mp3"},
    {"name": "lynx_793367", "url": "https://storage.nocodecult.io/sounds/lynx_793367.mp3"},
    {"name": "magnolia_282070", "url": "https://storage.nocodecult.io/sounds/magnolia_282070.mp3"},
    {"name": "moser_965048", "url": "https://storage.nocodecult.io/sounds/moser_965048.mp3"},
    {"name": "oddfellow_384078", "url": "https://storage.nocodecult.io/sounds/oddfellow_384078.mp3"},
    {"name": "orthodox_361440", "url": "https://storage.nocodecult.io/sounds/orthodox_361440.mp3"},
    {"name": "reggie_964382", "url": "https://storage.nocodecult.io/sounds/reggie_964382.mp3"},
    {"name": "rukia_707361", "url": "https://storage.nocodecult.io/sounds/rukia_707361.mp3"},
    {"name": "seraph_352471", "url": "https://storage.nocodecult.io/sounds/seraph_352471.mp3"},
    {"name": "serbian_873750", "url": "https://storage.nocodecult.io/sounds/serbian_873750.mp3"},
    {"name": "sound_01_707350", "url": "https://storage.nocodecult.io/sounds/sound_01_707350.mp3"},
    {"name": "spidey_468257", "url": "https://storage.nocodecult.io/sounds/spidey_468257.mp3"},
    {"name": "techdeck_088450", "url": "https://storage.nocodecult.io/sounds/techdeck_088450.mp3"},
    {"name": "tomrmx_125325", "url": "https://storage.nocodecult.io/sounds/tomrmx_125325.mp3"},
    {"name": "user_415328", "url": "https://storage.nocodecult.io/sounds/user_415328.mp3"},
    {"name": "vril_048646", "url": "https://storage.nocodecult.io/sounds/vril_048646.mp3"},
    {"name": "wevrix_790495", "url": "https://storage.nocodecult.io/sounds/wevrix_790495.mp3"},
    {"name": "winnie_886160", "url": "https://storage.nocodecult.io/sounds/winnie_886160.mp3"},
]


def get_random_sound() -> Dict[str, str]:
    """Returns a random sound dict with 'name' and 'url' keys."""
    return random.choice(TIKTOK_SOUNDS)


def get_random_sounds(count: int = 3) -> List[Dict[str, str]]:
    """Returns multiple random sounds for retry logic (no duplicates)."""
    if count >= len(TIKTOK_SOUNDS):
        return TIKTOK_SOUNDS.copy()
    return random.sample(TIKTOK_SOUNDS, count)
