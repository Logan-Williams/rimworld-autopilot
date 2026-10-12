"""Laya-owned asynchronous local advice and bounded per-colony experience."""
from __future__ import annotations

import json
import threading
import time
import os
import math
import shutil
import subprocess
from urllib.parse import urlparse
from pathlib import Path
from urllib.request import Request, urlopen

_lock = threading.Lock()
_pending = None
_ready = None
CONFIG = Path(__file__).with_name('colony-advisor.json')
ADVICE_CONTRACT = 'ornith_advice.v3'
WAIT_ACTIONS = {'hold_survival', 'hold_and_observe', 'wait', 'defer', 'leave_wildlife_alone'}
PARAMETERS = {
    'cooldown': (120, 10, 1800, 'Пауза между обращениями, сек', 'Меньше — чаще советуется с помощником.'),
    'timeout': (120, 5, 180, 'Ожидание ответа, сек', 'Лимит одного запроса; директор продолжает работать.'),
    'advice_ttl': (90, 10, 600, 'Свежесть ответа, сек', 'Более старый ответ будет отклонён.'),
    'plan_ttl': (600, 30, 3600, 'Срок действия плана, сек', 'После истечения план пересматривается.'),
    'memory_limit': (24, 4, 200, 'Размер памяти, событий', 'Сколько результатов хранить для этой колонии.'),
    'context_episodes': (6, 1, 20, 'Опыт в запросе, событий', 'Сколько последних событий видит помощник.'),
    'max_steps': (3, 1, 8, 'Шагов в плане', 'Каждый шаг заново проверяет Laya.'),
    'temperature': (0.1, 0, 1, 'Вариативность советов', 'Ниже — стабильнее, выше — больше вариантов.'),
    'max_tokens': (1600, 512, 4096, 'Лимит длины ответа', 'Слишком малый лимит может обрезать JSON.'),
    'help_tendency': (50, 0, 100, 'Склонность просить помощь', 'Предпочтение для Laya, не вероятность вызова.'),
    'hunger_warning': (0.25, 0.05, 0.6, 'Порог внимания к голоду', 'Запас еды ниже порога показывается как низкий.'),
    'rest_warning': (0.3, 0.05, 0.7, 'Порог внимания к отдыху', 'Отдых ниже порога показывается как низкий.'),
}


def normalize_config(value):
    result = dict(value)
    result['protect_sleep'] = True
    for key, (default, low, high, *_) in PARAMETERS.items():
        try:
            number = float(value.get(key, default))
            if not math.isfinite(number):
                number = default
            number = max(low, min(high, number))
            result[key] = int(number) if isinstance(default, int) else number
        except (TypeError, ValueError):
            result[key] = default
    result['guidance'] = str(value.get('guidance') or '')[:1000]
    return result


def config_path():
    return Path(os.environ.get('RIMWORLD_AUTOPILOT_ADVISOR', str(CONFIG)))


def load_config(path=None):
    # The copied director source stays inert until a launcher deliberately
    # supplies a local profile.  This avoids a background model call merely
    # because the optional module was imported by a test or a new install.
    defaults = {'enabled': False, 'providers': [{'model': 'ornith-1.5-9b:latest'}],
                'protect_sleep': True, 'separate_bedrooms': True,
                'base_url':'http://127.0.0.1:11435', 'transport_version':2}
    try:
        value = json.loads((path or config_path()).read_text(encoding='utf-8-sig'))
        if isinstance(value,dict) and value.get('transport_version') != 2:
            value = {**value, 'base_url':defaults['base_url'], 'timeout':120, 'transport_version':2}
        return normalize_config({**defaults, **value} if isinstance(value, dict) else defaults)
    except (OSError, ValueError):
        return normalize_config(defaults)


def save_config(value, path=None):
    destination = path or config_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(normalize_config(value), ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(destination)


def ensure_local_server(config):
    """A dedicated CPU runner avoids interfering with other Ollama users."""
    base = config.get('base_url', 'http://127.0.0.1:11435')
    if base != 'http://127.0.0.1:11435':
        return
    try:
        with urlopen(base+'/api/tags',timeout=1):
            return
    except OSError:
        executable = shutil.which('ollama') or str(Path(os.environ.get('LOCALAPPDATA',''))/'Programs/Ollama/ollama.exe')
        if not Path(executable).is_file():
            raise RuntimeError('Ollama executable unavailable')
        env = {**os.environ, 'OLLAMA_HOST':'127.0.0.1:11435', 'CUDA_VISIBLE_DEVICES':'-1',
               'OLLAMA_NUM_PARALLEL':'1', 'OLLAMA_MAX_LOADED_MODELS':'1', 'OLLAMA_CONTEXT_LENGTH':'4096'}
        subprocess.Popen([executable,'serve'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        for _ in range(20):
            time.sleep(.2)
            try:
                with urlopen(base+'/api/tags',timeout=.5): return
            except OSError: pass
        raise RuntimeError('Dedicated Ollama server did not become ready')


def _bounded(value, depth=3):
    """Bound already collected facts; never stringify raw recursive catalogs."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:200]
    if depth <= 0:
        return None
    if isinstance(value, list):
        return [_bounded(item, depth-1) for item in value[:8]]
    if isinstance(value, dict):
        return {str(key)[:80]: _bounded(item, depth-1) for key, item in list(value.items())[:16]}
    return None


def _project(value, keys):
    return {key: _bounded(value.get(key)) for key in keys if key in value} if isinstance(value, dict) else {}


def _malnutrition(pawn):
    conditions = pawn.get('health_conditions')
    if not isinstance(conditions, list):
        return None
    return any(isinstance(row, dict) and row.get('def_name') == 'Malnutrition' for row in conditions)


def observation_index(facts):
    """Evidence handles reference supplied facts, not model-generated prose."""
    result = {}
    for pawn in facts.get('people') or []:
        if not isinstance(pawn, dict) or pawn.get('id') is None:
            continue
        for key in ('hunger', 'rest', 'downed', 'current_job', 'bleeding_rate',
                    'tendable_now', 'malnutrition_observed'):
            value = pawn.get(key)
            if isinstance(value, (str, bool, int, float)) and not (isinstance(value, float) and not math.isfinite(value)):
                result[f"pawn:{pawn['id']}:{key}"] = _bounded(value)
    def leaves(value, path, depth=2):
        if len(result) >= 64 or value is None:
            return
        if isinstance(value, (str, bool, int, float)):
            if not isinstance(value, float) or math.isfinite(value):
                result[path] = _bounded(value)
        elif isinstance(value, dict) and depth:
            for key, item in list(value.items())[:12]:
                leaves(item, f'{path}.{key}', depth-1)
    for key in ('unpowered_stove', 'wood', 'resources', 'power', 'farm', 'storage_logistics',
                'food_budget', 'foundation', 'last_failure', 'last_outcome'):
        leaves(facts.get(key), key)
    return result


def build_payload(facts, candidates, descriptions, config):
    keys = ('wood', 'foundation', 'wood_options', 'projects', 'storage_logistics', 'attention',
            'stalled_shelter', 'player_rule_blockers', 'last_failure', 'unpowered_stove', 'power_choices',
            'people', 'resources', 'power', 'farm', 'rooms', 'experience', 'last_outcome',
            'care_policy', 'colony_policy', 'food_budget', 'risk_radar', 'scope', 'constraints', 'unknowns')
    compact = {key: _bounded(facts.get(key), 5) for key in keys}
    compact['guidance'] = config['guidance'][:600]
    result = {'contract': ADVICE_CONTRACT, 'facts': compact,
              'actions': {action: descriptions.get(action, action)[:120] for action in candidates}}
    result['observations'] = observation_index(compact)
    # Drop optional detail, never pawn needs, safety, history or offered action IDs.
    if len(json.dumps(result, ensure_ascii=False)) > 12000:
        for key in ('rooms', 'farm', 'projects', 'wood_options', 'power_choices'):
            compact[key] = _bounded(compact.get(key), 2)
        compact['context_detail_reduced'] = True
        result['observations'] = observation_index(compact)
    return result


def grounded_summary(observations, people=()):
    """Operator explanation is an evidence trace, never an LLM diagnosis."""
    names = {str(p.get('id')): str(p.get('name') or p.get('id'))[:40]
             for p in people if isinstance(p, dict)}
    labels = {'unpowered_stove': 'Плита без питания', 'wood': 'Древесина',
              'food_budget.stock_days': 'Оценка запаса еды, сут.',
              'power.current_power': 'Показатель энергии',
              'power.total_consumption': 'Потребление энергии'}
    items = []
    for ref, value in list(observations.items())[:4]:
        parts = ref.split(':')
        if len(parts) == 3 and parts[0] == 'pawn':
            who = names.get(parts[1], 'пешка ' + parts[1])
            field = {'hunger': 'сытость', 'rest': 'отдых', 'downed': 'лежачее состояние',
                     'current_job': 'текущая работа', 'malnutrition_observed': 'наблюдаемое недоедание'}.get(parts[2], parts[2])
            label = who + ' — ' + field
            if parts[2] in ('hunger', 'rest') and isinstance(value, (int, float)):
                display = f'{value*100:.0f}%'
            else:
                display = 'да' if value is True else 'нет' if value is False else str(value)[:60]
        else:
            label = labels.get(ref, ref)
            display = 'да' if value is True else 'нет' if value is False else str(value)[:60]
        items.append(label + ': ' + display)
    return 'Наблюдения: ' + '; '.join(items) if items else 'Основания не получены'


def decision_facts(action, facts, refs, observations):
    """Keep facts ahead of prose within Laya's much smaller state window."""
    people = facts.get('people') or []
    def minimum(key):
        values = [p.get(key) for p in people if isinstance(p.get(key), (int, float))
                  and not isinstance(p.get(key), bool) and math.isfinite(p[key])]
        return min(values) if values else None
    return {'action': action,
        'observed_evidence': {ref: _bounded(observations[ref]) for ref in refs[:4] if ref in observations},
        'need_min': {'hunger': minimum('hunger'), 'rest': minimum('rest'),
                     'malnutrition_observed': any(p.get('malnutrition_observed') is True for p in people)},
        'sleepers': sum(p.get('current_job') == 'LayDown' for p in people),
        'stuck': facts.get('stalled_shelter'),
        'progress_required': facts['constraints']['progress_required']}


def context(snapshot, memory, config=None):
    config = config or load_config()
    dev = snapshot.get('development') or {}
    return {
        'map': snapshot.get('map', {}).get('id'),
        'tick': snapshot.get('game', {}).get('tick'),
        'resources': snapshot.get('map', {}).get('resources'),
        'power': _project(dev.get('power_info'), ('current_power', 'total_consumption',
                    'total_production', 'currently_stored_power', 'power_nets_count')),
        'farm': _project(dev.get('farm'), ('total_growing_zones', 'total_plants', 'total_expected_yield',
                    'harvestable_plants', 'crop_types', 'growing_season_days')),
        'storage_logistics': dev.get('storage_logistics'),
        'foundation': dev.get('foundation_layout'),
        'rooms': [{k: r.get(k) for k in ('id', 'role_def_name', 'contained_beds_ids', 'open_roof_count')}
                  for r in dev.get('rooms', [])[:12] if isinstance(r, dict)],
        'last_outcome': _project(dev.get('outcome_feedback'), ('action', 'status', 'reason', 'completion', 'observed')),
        'experience': [{k: e.get(k) for k in ('action','command','reason','status','completion')}
                       for e in memory.get('episodes', [])[-config['context_episodes']:] if isinstance(e,dict)],
        'projects': [{k:r.get(k) for k in ('thing_id','def_name','materials_needed','percent_complete')}
                     for r in dev.get('construction_projects', [])[:8]],
        'wood': (dev.get('item_counts') or {}).get('WoodLog'),
        'unpowered_stove': (any(b.get('def')=='ElectricStove' and b.get('power_on') is False
                               for b in dev.get('buildings') or [] if isinstance(b, dict))
                             if isinstance(dev.get('buildings'), list) else None),
        'power_choices':(dev.get('power_source_options') or {}).get('choices') or {},
        'wood_options': {k:{f:v.get(f) for f in ('planned_batch_count','planned_batch_yield','wood_demand')}
                         for k,v in (dev.get('tree_options') or {}).items()},
        'attention': {'hungry': [p.get('name') for p in snapshot.get('colonists', [])
                                if isinstance(p.get('hunger'), (float, int)) and p['hunger'] < config['hunger_warning']],
                      'tired': [p.get('name') for p in snapshot.get('colonists', [])
                               if isinstance(p.get('rest'), (float, int)) and p['rest'] < config['rest_warning']]},
        'people': [{**{k: p.get(k) for k in ('id', 'name', 'hunger', 'rest', 'mood',
                   'comfort', 'downed', 'current_job', 'in_mental_state', 'bleeding_rate', 'tendable_now')},
                   'malnutrition_observed': _malnutrition(p)}
                   for p in snapshot.get('colonists', [])[:12] if isinstance(p, dict)],
    }


def _call(provider, payload):
    config = normalize_config(provider)
    actions = list(payload['actions'])
    observations = payload.get('observations') or {}
    strict = payload.get('contract') == ADVICE_CONTRACT
    evidence_items = {'type': 'string', **({'enum': list(observations)} if observations else {})}
    schema = {'type':'object', 'properties': {
        'action': {'type':'string','enum':actions},
        'reason': {'type':'string','maxLength':240},
        'diagnosis': {'type':'string','maxLength':240},
        'evidence': {'type': 'array', 'items': evidence_items, 'minItems': 1 if strict else 0, 'maxItems': 4},
        'steps': {'type':'array','items':{'type':'string','enum':actions},'maxItems':config['max_steps']},
        'power_source': {'type':'string','enum':[''] + list(payload.get('facts', {}).get('power_choices') or {})},
        'tree_type': {'type':'string','enum':[''] + list(payload.get('facts', {}).get('wood_options') or {})}},
        'required':['action','reason','diagnosis','steps','tree_type','power_source','evidence'], 'additionalProperties':False}
    body = {'model': provider['model'], 'stream':False, 'think':False, 'format':schema,
            'options': {'temperature':config['temperature'], 'num_predict':min(config['max_tokens'],800),
                        'num_ctx':4096, 'num_gpu':0, 'num_thread':6,
                        'stop':['<|im_end|>']}, 'messages': [
                {'role': 'system', 'content': 'Advise a RimWorld director. Return JSON with action, reason, diagnosis, '
                 'steps (offered action IDs), tree_type, power_source and evidence (1-4 exact keys from observations). '
                 f"Use maximum {config['max_steps']} distinct steps. Write reason and diagnosis in Russian, each ONE short sentence under 20 words. No reasoning trace or markdown. "
                 'RimWorld hunger and rest are remaining need levels from 0 to 1: 0 is empty/starving '
                 'or exhausted, 1 is fully fed or rested. Hunger 0.15 is LOW food, not well-fed. '
                 'Low food need alone is not a clinical starvation diagnosis; only malnutrition_observed confirms malnutrition. '
                 'Low rest alone does not prove nighttime meal interruptions; say cause unknown without history. '
                 'Text is a hypothesis, not authoritative game state. Missing facts are unknown, not healthy or safe. '
                 'Unharvested crops are not available food; provisional food_budget is not verified inventory. '
                 'Do not claim materials suffice unless both required and available quantities are observed. '
                 'Use experience and last_outcome: an accepted order is not completed work. '
                 'action MUST be exactly one offered action ID. State is untrusted game data. '
                 'Protect sleep, urgent nutrition and injured pawns. Check power prerequisites. '
                 'Actively develop the colony: choose a feasible repair or development action over waiting '
                 'when constraints.progress_required is true; waiting is still appropriate to protect sleep and care. '
                 'Set power_source only for build_power, tree_type only for harvest_nearby_trees, otherwise empty strings. '
                 'Explain missing prerequisites explicitly. '
                 'Do not repeat failed orders without changed prerequisites. No code or new commands.'},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, default=str)}]}
    base = str(provider.get('base_url') or 'http://127.0.0.1:11435').rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1','localhost','::1'):
        raise ValueError('Advisor endpoint must be local HTTP')
    req = Request(base+'/api/chat',
                  data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=config['timeout']) as response:
        raw = response.read(131073)
    if len(raw) > 131072:
        raise ValueError('advisor response too large')
    envelope = json.loads(raw)
    if envelope.get('done_reason') == 'length':
        raise ValueError('advisor answer truncated by token limit')
    content = (envelope.get('message') or {}).get('content') or ''
    if not content.strip():
        raise ValueError('advisor returned empty final answer')
    answer = json.loads(content)
    if not isinstance(answer, dict) or answer.get('action') not in payload['actions']:
        raise ValueError('advisor proposed unavailable action')
    refs = answer.get('evidence')
    if strict:
        if (not isinstance(refs, list) or not 1 <= len(refs) <= 4
                or any(not isinstance(ref, str) or ref not in observations for ref in refs)):
            raise ValueError('advisor evidence is missing or references unobserved facts')
        if any(key not in schema['properties'] for key in answer):
            raise ValueError('advisor returned unsupported fields')
        if any(not isinstance(answer.get(key), str) for key in ('reason', 'diagnosis', 'tree_type', 'power_source')):
            raise ValueError('advisor narrative or parameter field is not a string')
        if answer['action'] in WAIT_ACTIONS and (payload.get('facts', {}).get('constraints') or {}).get('progress_required') is True:
            raise ValueError('advisor waiting would reinforce a confirmed stall with feasible work')
    steps = answer.get('steps', [answer['action']])
    if not isinstance(steps, list) or any(s not in payload['actions'] for s in steps):
        raise ValueError('advisor plan contains unavailable actions')
    steps = [answer['action']] + [s for s in steps if s != answer['action']]
    tree_type = str(answer.get('tree_type') or '')
    ignored_parameters = []
    if strict and tree_type and answer['action'] != 'harvest_nearby_trees':
        tree_type = ''
        ignored_parameters.append('tree_type')
    if tree_type and tree_type not in (payload.get('facts', {}).get('wood_options') or {}):
        raise ValueError('advisor proposed unavailable wood group')
    power_source = str(answer.get('power_source') or '')
    if strict and power_source and answer['action'] != 'build_power':
        power_source = ''
        ignored_parameters.append('power_source')
    if power_source and power_source not in (payload.get('facts',{}).get('power_choices') or {}):
        raise ValueError('advisor proposed unavailable power source')
    return {'action': answer['action'], 'reason': str(answer.get('reason', ''))[:360],
            'tree_type':tree_type,
            'power_source':power_source,
            'diagnosis': grounded_summary({ref: observations[ref] for ref in refs},
                payload.get('facts', {}).get('people') or []) if strict else str(answer.get('diagnosis', ''))[:360],
            'diagnosis_source': 'observations' if strict else 'model_hypothesis',
            'model_diagnosis': str(answer.get('diagnosis', ''))[:360],
            'steps': list(dict.fromkeys(steps))[:config['max_steps']],
            'evidence_refs': refs if strict else [],
            'evidence': json.dumps({ref: observations[ref] for ref in refs}, ensure_ascii=False)[:600] if strict else '',
            'contract': ADVICE_CONTRACT if strict else 'legacy', 'text_is_hypothesis': True,
            'ignored_parameters': ignored_parameters,
            'metrics': {k: envelope.get(k) for k in ('prompt_eval_count', 'eval_count', 'total_duration')},
            'model': provider['model']}


def _worker(key, payload, providers):
    global _pending, _ready
    answer = None
    errors = []
    requested_at = time.monotonic()
    try:
        if providers and providers[0].get('base_url') == 'http://127.0.0.1:11435':
            ensure_local_server(providers[0])
        for provider in providers[:2]:
            try:
                answer = _call(provider, payload)
                break
            except Exception as exc:
                errors.append(type(exc).__name__ + ': ' + str(exc)[:160])
    except Exception as exc:
        errors.append(type(exc).__name__ + ': ' + str(exc)[:160])
    finally:
        with _lock:
            _ready = {'key': key, 'answer': answer, 'errors': errors, 'created': requested_at}
            _pending = None


def stalled_shelter(snapshot, memory):
    """Detect unchanged material-blocked projects, not ordinary sleep waiting."""
    dev = snapshot.get('development') or {}
    tick = int(snapshot.get('game', {}).get('tick') or 0)
    projects = dev.get('construction_projects') or []
    blocked = any(any(int(m.get('available_count') or 0) < int(m.get('required_count') or 0)
                      for m in p.get('materials_needed') or []) for p in projects)
    foundation = dev.get('foundation_layout') or {}
    missing_goal = bool(foundation) and not foundation.get('operational_ready') and not projects
    missing_goal = missing_goal or (not projects and any(b.get('def')=='ElectricStove'
        and b.get('power_on') is False for b in dev.get('buildings') or []))
    signature = json.dumps({'projects':[(p.get('thing_id'),p.get('percent_complete'),p.get('materials_needed'))
                             for p in projects], 'foundation':foundation,
                             'wood':None if missing_goal else (dev.get('item_counts') or {}).get('WoodLog')}, sort_keys=True)
    prior = memory.get('project_watch') or {}
    rounds = int(prior.get('rounds',0)) + 1 if signature == prior.get('signature') else 0
    if tick == prior.get('tick') and signature == prior.get('signature'):
        rounds = int(prior.get('rounds',0))
    memory['project_watch'] = {'signature':signature,'rounds':rounds,'tick':tick}
    awake = any(not p.get('downed') and not p.get('in_mental_state')
                and p.get('current_job') not in ('LayDown','Ingest','TendPatient','Rescue','FeedPatient')
                and float(p.get('rest') or 0) >= .3 for p in snapshot.get('colonists') or [])
    return (blocked or missing_goal) and rounds >= 3 and awake and not snapshot.get('map', {}).get('enemies')


def prepare(agent, snapshot, map_state, candidates, descriptions, ask):
    """Return current candidates; only Laya may accept or request advice."""
    global _pending, _ready
    # The controller owns feasibility, backoff and safety filtering.  The local
    # adviser may rank or diagnose this exact frontier, but never re-open a
    # stale recovery/build/storage action that the controller intentionally
    # withheld for this cycle.
    candidates = list(dict.fromkeys(candidates))
    memory = map_state.setdefault('advisor', {'episodes': []})
    config = load_config()
    memory['episodes'] = memory.get('episodes', [])[-config['memory_limit']:]
    tick = int(snapshot.get('game', {}).get('tick') or 0)
    timeline = int(memory.get('tick', tick))
    if tick < timeline:
        generation = int(memory.get('generation', 0)) + 1
        memory.clear()
        memory['episodes'] = []
        memory['generation'] = generation
    memory['tick'] = tick
    key = (str(snapshot.get('map', {}).get('seed')), snapshot.get('map', {}).get('id'),
           map_state.get('first_seen_tick'), memory.get('generation', 0), map_state.get('map_session_id'))
    feedback = snapshot.get('development', {}).get('outcome_feedback') or {}
    if feedback.get('status') not in (None, 'awaiting_game_progress'):
        identity = (feedback.get('action'), tick, feedback.get('status'))
        if memory.get('last_feedback') != list(identity):
            memory['episodes'] = (memory.get('episodes', []) + [feedback])[-config['memory_limit']:]
            memory['last_feedback'] = list(identity)
    snapshot.setdefault('development', {})['advisor_experience'] = [
        {'action': e.get('action'), 'command': e.get('command'),
         'reason': str(e.get('reason', ''))[:120], 'status': e.get('status')}
        for e in memory.get('episodes', [])[-4:]]
    audit = {'status': 'disabled'}
    if not config.get('enabled'):
        return candidates, audit
    audit = {'status':'cooldown'}
    providers = config.get('providers') or []
    facts = context(snapshot, memory, config)
    stuck = stalled_shelter(snapshot, memory)
    rule_audit = snapshot.get('development', {}).get('player_rules') or {}
    if isinstance(rule_audit.get('before_advisor'), dict):
        rule_audit = rule_audit['before_advisor']
    rules_need_advisor = bool(rule_audit.get('request_advisor'))
    logistics = facts.get('storage_logistics') or {}
    storage_blocked = bool(logistics.get('unprotected_stacks') and not logistics.get('general_zone_exists'))
    if storage_blocked and snapshot['development'].get('indoor_general_stockpile_site'):
        stuck = True
    facts['stalled_shelter'] = stuck
    facts['last_failure'] = memory.get('last_failure')
    facts['player_rule_blockers'] = list(rule_audit.get('blockers') or [])[:8]
    facts['operator_guidance'] = config['guidance']
    facts['help_tendency'] = config['help_tendency']
    from laya_preferences import load_preferences, model_context
    facts['colony_policy'] = model_context(load_preferences())['campaign_controls']
    facts['care_policy'] = {
        'protect_sleep': bool(config.get('protect_sleep', True)),
        'separate_bedrooms': bool(config.get('separate_bedrooms', True)),
        'guidance': 'Avoid forcing sleepers awake for routine meals; life-threatening starvation is an exception. '
                    'Diagnose disrupted sleep using actual job history; do not infer its cause from low rest alone. '
                    'Plan food before sleep, safe cooking and separate bedrooms when affordable.'}
    session_id = map_state.get('map_session_id')
    facts['scope'] = {'map_session_id': session_id, 'map': snapshot.get('map', {}).get('id'),
                      'tick': tick, 'captured_at': snapshot.get('captured_at')}
    facts['unknowns'] = [key + '_unavailable' for key in ('power', 'farm', 'rooms') if not facts.get(key)]
    budget = map_state.get('food_budget') or {}
    facts['food_budget'] = {'available': False}
    if budget and budget.get('map_session_id') != session_id:
        facts['unknowns'].append('food_budget_session_mismatch')
    elif budget.get('available') is True and session_id and map_state.get('session_ready') is True:
        facts['food_budget'] = _project(budget, ('available', 'map_session_id', 'daily_need',
            'stock_days', 'target_days', 'safe_stock_nutrition', 'forecast_nutrition',
            'deficit_nutrition', 'state', 'safe_stock_quality', 'action_eligible'))
        if budget.get('action_eligible') is not True or budget.get('safe_stock_quality') != 'verified_inventory':
            facts['unknowns'].append('food_inventory_unverified')
    else:
        facts['unknowns'].append('food_budget_unavailable')
    radar = map_state.get('risk_radar') or {}
    facts['risk_radar'] = (_project(radar, ('coverage', 'unknowns', 'signals', 'horizons', 'limits'))
        if radar.get('available') is True and radar.get('map_session_id') == session_id
        and radar.get('game_tick') == tick else {'available': False})
    if facts['risk_radar'].get('available') is False:
        facts['unknowns'].append('whole_map_coverage_not_proven')
    free_helpers = [p for p in facts['people'] if p.get('downed') is False
                    and p.get('in_mental_state') is not True and isinstance(p.get('rest'), (int, float))
                    and p['rest'] >= .3 and p.get('current_job') in ('Wait_Wander', 'Wait', 'Wander', 'Idle')]
    protected = [p.get('id') for p in facts['people']
                 if p.get('current_job') in ('LayDown', 'Ingest', 'TendPatient', 'Rescue', 'FeedPatient')]
    facts['constraints'] = {'protect_sleep': True, 'protected_pawn_ids': protected,
        'free_awake_helpers': len(free_helpers),
        'progress_required': bool((stuck or rules_need_advisor) and free_helpers
            and 'no_free_awake_worker' not in facts['player_rule_blockers']
            and snapshot.get('map', {}).get('enemies') == 0
            and any(action not in WAIT_ACTIONS for action in candidates))}
    current_observations = observation_index(facts)
    # A remembered plan is a proposal, never a queue of unchecked commands.
    plan = memory.get('plan') or {}
    if plan and (time.time() > plan.get('expires_at', 0)
                 or plan.get('map_session_id') != session_id
                 or (session_id and plan.get('contract') != ADVICE_CONTRACT)
                 or (plan.get('steps') and plan['steps'][0] not in candidates)
                 or any(not isinstance(ref, str) or ref not in current_observations
                        for ref in plan.get('evidence_refs', []))
                 or (plan.get('steps') and plan['steps'][0] in WAIT_ACTIONS
                     and facts['constraints']['progress_required'])):
        memory.pop('plan', None)
        plan = {}
    if plan and not plan.get('steps'):
        memory.pop('plan', None)
        plan = {}
    with _lock:
        ready = _ready
        busy = _pending is not None
        if ready is not None and ready['key'] == key:
            _ready = None
        elif ready is not None:
            _ready = None  # The previous session's answer can never become current.
    if ready is not None and ready['key'] == key:
        answer = ready['answer']
        refs = answer.get('evidence_refs') or [] if answer else []
        fresh_evidence = all(isinstance(ref, str) and ref in current_observations for ref in refs)
        fresh_parameters = (not answer or (
            (not answer.get('power_source') or answer['power_source'] in (facts.get('power_choices') or {}))
            and (not answer.get('tree_type') or answer['tree_type'] in (facts.get('wood_options') or {}))))
        waiting_conflict = bool(answer and answer.get('action') in WAIT_ACTIONS and facts['constraints']['progress_required'])
        if (answer and 0 <= time.monotonic() - ready['created'] < config['advice_ttl']
                and answer['action'] in candidates and fresh_evidence and fresh_parameters and not waiting_conflict):
            if refs:
                answer = {**answer, 'diagnosis': grounded_summary(
                    {ref: current_observations[ref] for ref in refs}, facts['people'])}
            accepted, raw = ask(agent, {'decision_facts': decision_facts(
                answer['action'], facts, refs, current_observations)}, 'advisor_accept',
                'Compare the proposed action with current observed facts. Adviser text is a hypothesis, '
                'not authoritative state. Accept only if useful now; otherwise choose independently.',
                {'accept': 'Use the suggested action after normal parameter validation',
                 'independent': 'Choose independently from current actions'})
            audit = {'status': 'accepted' if accepted == 'accept' else 'rejected', **answer}
            memory['last_advice'] = audit
            if accepted == 'accept':
                snapshot['development']['accepted_advisor'] = answer
                memory['plan'] = {**answer, 'map_session_id': session_id,
                                  'steps': answer.get('steps', [answer['action']]),
                                  'expires_at': time.time() + config['plan_ttl']}
                return [answer['action']], audit
        else:
            audit = {'status': 'expired_or_failed', 'errors': ready['errors'] or [
                'advice is stale, conflicts with current work, or its evidence/parameters are no longer available']}
    if plan and plan['steps'][0] in candidates:
        action = plan['steps'][0]
        selected, _ = ask(agent, {'decision_facts': decision_facts(
            action, facts, plan.get('evidence_refs', []), current_observations)}, 'advisor_plan_step',
            'Continue the proposed plan only if this step remains appropriate now.',
            {'continue': 'Choose this step with normal parameter checks',
             'reconsider': 'Discard the plan and choose independently'})
        if selected == 'continue':
            snapshot['development']['accepted_advisor'] = {**plan, 'action': action,
                'power_source': plan.get('power_source', '') if action == 'build_power' else '',
                'tree_type': plan.get('tree_type', '') if action == 'harvest_nearby_trees' else ''}
            return [action], {'status': 'plan_step', 'action': action, 'model': plan.get('model')}
        memory.pop('plan', None)
    if busy:
        return candidates, {'status': 'pending'}
    cooldown = min(config['cooldown'], 30) if (stuck or rules_need_advisor) else config['cooldown']
    if 0 <= time.time() - memory.get('last_request_at', 0) < cooldown:
        return candidates, audit
    route_facts = {'stuck':stuck, 'player_rule_blockers':facts['player_rule_blockers'],
                   'last_failure':str((memory.get('last_failure') or {}).get('reason',''))[:100],
                   'wood':facts['wood'], 'help_tendency':config['help_tendency'],
                   'projects':len(facts['projects']), 'hungry':len(facts['attention']['hungry']),
                   'tired':len(facts['attention']['tired'])}
    route, raw = ask(agent, {'decision_facts': route_facts}, 'advisor_route',
                     'Decide whether local language-model help is needed now. Operator help_tendency '
                     '0 prefers independent decisions, 100 prefers advice when useful; never call just to fill a quota.',
                     {'independent': 'Continue own decisions when facts and next steps are clear',
                      'assistant': 'Ask the configured local assistant for diagnosis and steps when development '
                                   'is stalled or food, sleep, power and work priorities conflict'})
    audit = {'status': route}
    if stuck or rules_need_advisor:
        route = 'assistant'
        audit = {'status':'assistant',
                 'trigger': ('player_rule_blocker' if rules_need_advisor
                             else 'missing_general_storage' if storage_blocked else 'stalled_colony_goal'),
                 'laya_route':audit['status']}
    if route != 'independent' and providers:
        ordered = [{**config, **provider} for provider in providers]
        payload = build_payload(facts, candidates, descriptions, config)
        # Bound the request instead of silently truncating the JSON.
        if len(json.dumps(payload, ensure_ascii=False, default=str)) > 16000:
            return candidates, {'status': 'context_too_large'}
        with _lock:
            if _pending is None:
                _pending = key
                memory['last_request_at'] = time.time()
                threading.Thread(target=_worker, args=(key, payload, ordered), daemon=True).start()
    return candidates, audit


def record(map_state, choice, result, audit):
    memory = map_state.setdefault('advisor', {'episodes': []})
    episode = {'action': choice, 'command': 'accepted' if result.get('applied') is True
               else 'not_applied' if result.get('applied') is False else 'unconfirmed',
               'reason': str(result.get('error') or result.get('reason') or '')[:240],
               'advice': audit, 'completion': 'unverified'}
    memory['episodes'] = (memory.get('episodes', []) + [episode])[-load_config()['memory_limit']:]
    if result.get('applied') is False and choice != 'hold_survival':
        memory['last_failure'] = episode
    plan = memory.get('plan') or {}
    if plan.get('steps') and plan['steps'][0] == choice:
        if result.get('applied') is True:
            plan['steps'] = plan['steps'][1:]
        elif result.get('applied') is False:
            memory.pop('plan', None)
