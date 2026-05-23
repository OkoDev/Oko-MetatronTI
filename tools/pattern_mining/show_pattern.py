"""Quick pattern lookup: python show_pattern.py [pattern_id|all|tier]

Examples:
  python show_pattern.py T4_S_09       # одна детальная карточка
  python show_pattern.py T7            # все T7 patterns
  python show_pattern.py SHORT         # все SHORT patterns
  python show_pattern.py all           # full table compact
"""
import sys
sys.path.insert(0, 'e:/MTF BOT/CURSOR/crypto_volume_bot')
try: sys.stdout.reconfigure(encoding='utf-8')
except: pass

from core.confirmations.arch104_patterns import ARCH104Registry
reg = ARCH104Registry()

arg = sys.argv[1] if len(sys.argv) > 1 else 'all'


def card(p):
    print(f"\n=== {p.id} ===")
    print(f"  direction: {p.direction}")
    print(f"  detection_tf: {p.detection_tf}")
    print(f"  weight: {p.weight}, priority: {p.priority}")
    print(f"  test: n={p.test_n}  avgR={p.test_avgR:+.2f}  WR={p.test_WR:.1f}%")
    print(f"  tp_strategy: {p.tp_strategy}  time_exit: {p.time_exit_hours}h")
    print(f"  anchors ({len(p.anchor_factors)}):")
    for a in p.anchor_factors:
        print(f"    - {a}")


def compact_table(patterns):
    print(f"{'id':<28} {'dir':<5} {'tf':<4} {'w':<3} {'n':>5} {'avgR':>6} {'WR':>5}  anchors")
    print("-" * 130)
    for p in sorted(patterns, key=lambda x: (x.direction, -x.weight)):
        anch = ' + '.join(p.anchor_factors)[:75]
        print(f"{p.id:<28} {p.direction:<5} {p.detection_tf:<4} {p.weight:<3} "
              f"{p.test_n:>5} {p.test_avgR:>+6.2f} {p.test_WR:>4.1f}%  {anch}")


# Routing
if arg == 'all':
    print(f"Registry: {len(reg.patterns)} patterns")
    print(f"  LONG: {len(reg.list_by_direction('LONG'))}, SHORT: {len(reg.list_by_direction('SHORT'))}")
    print()
    compact_table(reg.patterns.values())
elif arg in ('LONG', 'SHORT'):
    pats = reg.list_by_direction(arg)
    print(f"{arg}: {len(pats)} patterns")
    compact_table(pats)
elif arg in ('T1','T2','T2L','T4','T5','T6','T7','D2','L1','L2','L3','S1','S2','S3','S4','S8'):
    pats = [p for p in reg.patterns.values() if p.id.startswith(arg)]
    print(f"{arg}*: {len(pats)} patterns")
    compact_table(pats)
elif arg in reg.patterns:
    card(reg.get(arg))
else:
    print(f"Unknown: {arg}")
    print("Usage: <pattern_id> | LONG | SHORT | T1|T2|T2L|D2|T4|T5|T6|T7 | all")
