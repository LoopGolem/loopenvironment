# SPDX-License-Identifier: Apache-2.0
"""Interactive structured selection using only the authenticated Bridge API."""
import json


def choose(items, label, prompt, output):
    if not items:
        print('Nenhum resultado nesta página.', file=output)
        return None
    for index, item in enumerate(items, 1):
        print(f'{index}. {label(item)}', file=output)
    try:
        value = int(prompt('Número ou Enter para voltar: '))
    except ValueError:
        return None
    return items[value - 1] if 1 <= value <= len(items) else None


def teach(rpc, prompt, output, session='desktop'):
    def call(method, **params):
        return rpc.call(method, session=session, **params)

    app = choose(call('app.list')['applications'], lambda row: row['app'],
                 prompt, output)
    if app is None:
        return 1
    window = choose([row for row in call('window.list', app=app['app'])['windows'] if row['ref']],
                    lambda row: f"{row['application_id']} / {row['window']}",
                    prompt, output)
    if window is None:
        return 1
    offset = 0
    search = prompt('Filtrar por nome, papel ou ação (Enter para todos): ').strip().casefold()
    selected = None
    while offset is not None:
        page = call('element.tree', ref=window['ref'], offset=offset, depth=40)
        items = [row for row in page['elements']
                 if search in ' '.join([row['role'], row['name'], *row['actions']]).casefold()]
        if search:
            for row in page['elements']:
                if (row not in items and row['actions_truncated'] and 'protected' not in row['state']
                        and row['role'] != 'password text'):
                    native_actions = call('element.actions', ref=row['ref'])['actions']
                    if search in ' '.join(native_actions).casefold():
                        items.append(row)
        selected = choose(items, lambda row: f"{row['role']} / {row['name']} / {row['actions']}",
                          prompt, output)
        if selected:
            break
        offset = page['next']
        if offset is not None and prompt('Próxima página? [s/N] ').strip().lower() != 's':
            break
    if selected is None:
        return 1
    current = call('element.refresh', ref=selected['ref'])
    action_list = call('element.actions', ref=current['ref'])
    print(json.dumps(dict(element=current, actions=action_list), ensure_ascii=False, indent=2),
          file=output, flush=True)
    meaning = prompt('Significado: ')
    operation = prompt('Ação semântica sugerida (opcional): ')
    conditions = prompt('Condições (opcional): ')
    warnings = prompt('Alertas (opcional): ')
    if prompt('Gravar a evidência atual? [s/N] ').strip().lower() != 's':
        return 1
    live = call('element.refresh', ref=current['ref'])
    result = call('teach.create', ref=live['ref'], meaning=meaning, operationHint=operation,
                  conditions=conditions, warnings=warnings)
    print(json.dumps(result, ensure_ascii=False), file=output)
    return 0
