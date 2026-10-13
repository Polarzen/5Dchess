"""An isolated curriculum. Every practice transition uses the real rules engine."""
from copy import deepcopy
from itertools import permutations, product

from src.engine import ActionRules, BoardCoord, FiveDEngine, Position, Timeline
from src.utils.constants import ChessColor


def _position(lane, time, pieces=None, unmoved=()):
    board = [["" for _ in range(8)] for _ in range(8)]
    for (x, y), char in ({(0, 7): 'K', (7, 0): 'k'} | (pieces or {})).items():
        board[y][x] = char
    return Position(board=board, timeline_id=lane, time_point=time,
                    turn=BoardCoord.legacy_side_for_time_point(time), unmoved_pawns=set(unmoved))


def _engine(*positions):
    engine = FiveDEngine()
    engine.timeline_manager.timelines = {}
    for pos in positions:
        engine.timeline_manager.timelines.setdefault(pos.timeline_id, Timeline(pos.timeline_id)).add_position(pos)
    engine.current_action = ActionRules.begin(ChessColor.WHITE, engine.timeline_manager.timelines)
    return engine


def _plan(engine, specs, serialize, move_payload):
    """Fail closed if a practice move or final submission stops being legal."""
    engine = deepcopy(engine)
    steps = []
    for source, destination in specs:
        pos = engine.timeline_manager.timelines[source[0]].positions[source[1]]
        moves = engine.get_legal_moves_from_square(pos, source[2], source[3])
        move = next(m for m in moves if (m.destination.timeline, m.destination.board.legacy_time_point,
                                        m.to_x, m.to_y) == destination)
        before = serialize(engine)
        if not engine.execute_action_move(move):
            raise RuntimeError('Tutorial move rejected')
        recorded = engine.move_history[-1]
        after_move = serialize(engine)
        steps.append(dict(move=move_payload(recorded), before=before, after_move=after_move))
    if not engine.submit_action():
        raise RuntimeError('Tutorial submission rejected')
    return dict(steps=steps, after_submit=serialize(engine))


def _quiz(prompt, answers, correct, explanation):
    return dict(prompt=prompt, answers=answers, correct=correct, explanation=explanation)


PIECE_GUIDE = [
    ['车 ♖', '横走或竖走任意格', '只改变一个方向：也能只改变时间，或只改变时间线。'],
    ['象 ♗', '斜走，横竖距离相同', '恰好改变两个方向，距离相同；例如跨一条线，同时向右一格。'],
    ['后 ♕', '直走或斜走任意格', '同时改变一至四个方向；所有改变的距离相同。'],
    ['王 ♔', '向周围走一格', '可改变一至四个方向，每个只走一步；仍须保证王安全。'],
    ['马 ♘', '一个方向两格，另一个一格，可以跳子', '任意两个方向组成 2＋1；例如跨一条线，同时向右两格。'],
    ['兵 ♙', '向前直走，斜前方吃子；未动过可走两格', '还可沿时间线前进：白方向更小的 L，黑方向更大的 L。'],
]


def build_lessons(serialize, move_payload):
    ordinary = FiveDEngine()
    two_pawns = _engine(*[_position(lane, 0, {(4, 6): 'P'}, [(4, 6)]) for lane in (0, 1)])
    crossing = _engine(_position(0, 0, {(3, 4): 'R'}), _position(1, 0))
    branching = _engine(_position(0, 0), _position(0, 1), _position(0, 2, {(3, 4): 'R'}))
    overview = _engine(_position(0, 0), _position(0, 1), _position(0, 2), _position(1, 0))
    present = _engine(_position(0, 4), _position(1, 2), _position(2, 0))
    unsafe = _engine(_position(0, 1, {(7, 7): 'r'}))

    def practice(engine, *moves):
        return [_plan(engine, moves, serialize, move_payload)]

    lessons = [
        dict(id='welcome', title='从普通棋到时线棋局', stage='认识规则',
             description='这是国际象棋的时空变体，使用王、后、车、象、马、兵，和中国象棋的将、士、炮不同。不熟悉国际象棋也可以从这里开始。',
             points=['目标仍是将死对方：对方处于将军，而且找不到任何完整合法行动。没有合法行动但未被将军是逼和。',
                     '普通国际象棋只有一张当前棋盘；这里会保留过去，并出现平行时间线。每张棋盘不是一场独立比赛。',
                     '普通棋一手之后换人；这里一个回合称为“行动”，可能需要走好几张棋盘，最后手动提交。',
                     '棋子不仅能在格子间走，还能按各自走法跨时间、跨时间线。保护王时也要考虑这些方向。'],
             quiz=_quiz('以下哪项是这款游戏的关键区别？', ['走完一个棋子总会自动换人', '可以跨棋盘走子，一个行动可能包含多次走子', '每条支线各自算输赢'], 1,
                        '所有时间线共同组成一场对局。走子后先看红框与王安全，最后提交才换人。')),
        dict(id='read-boards', title='认清棋盘与时间', stage='认识规则',
             description='棋盘内横向是 a 到 h，纵向是 1 到 8。棋盘外横向是时间 T，纵向是时间线 L。下面按时间排列练习棋盘，标签与正式对局一致。',
             points=['L0 是主线，L+1、L−1 等是支线。白方产生正编号支线，黑方产生负编号支线。',
                     'T0 白方 → T0 黑方 → T1 白方：同一 T 还有白、黑两个阶段。棋盘标题的颜色是该棋盘阶段；上方“行动方”才表示现在谁操作。',
                     '每条线最新的一张棋盘才可作为出发点，且要轮到你的颜色；历史棋盘只可能成为合法落点。',
                     '红框＝目前必须推进；紫色标签＝当前时刻；灰色历史＝不能选子。当前时刻由活动线时间最早的最新棋盘决定。'],
             snapshot=serialize(overview),
             quiz=_quiz('白方现在能从 L0 的 T0 白方历史棋盘选子吗？', ['能，标题写着白方就可以', '不能，它已有后继；只能把它当作可能的落点', '能，历史棋盘可以任意改写'], 1,
                        '“白方阶段”还不够，出发棋盘必须是该时间线最新棋盘。历史保持不变。')),
        dict(id='first-turn', title='走第一手，再提交', stage='基础操作',
             description='先体验熟悉的普通走子：把白兵从 e2 走到 e4。兵首次可以前进两格，但中途与落点必须为空。',
             points=['点击亮框白兵，再点击蓝色格子。落子后出现黑方阶段的新棋盘，旧棋盘保留。',
                     '新棋盘轮到黑方，不等于已经全局换人。你仍须点击“提交行动”。'],
             plans=practice(ordinary, ((0, 0, 4, 6), (0, 0, 4, 4))),
             success='白兵已走到 e4，提交后行动方变成黑方。这就是最短的完整行动。',
             quiz=_quiz('什么时候才真正交给对手？', ['棋子一落下', '点击“提交行动”且提交成功后'], 1, '落子产生后继棋盘，提交结束整个行动。')),
        dict(id='pieces', title='认棋子，试试马', stage='基础操作',
             description='下面是六种棋子的速查表。先练习白马 g1 → f3：马可以越过挡在面前的兵。表格右列在后面的时空练习中会用到。',
             points=['棋子不能落到己方棋子上；落到敌方棋子上就是吃子。车、象、后的路径被棋子挡住就不能穿过，马可以跳过中间格。',
                     '本项目兵到对方底线自动升后。吃过路兵限同一棋盘、对手刚双步后的机会；王车易位还需要易位权、通路为空且王不穿过受攻击格。初学时以合法落点为准。'],
             piece_guide=PIECE_GUIDE,
             plans=practice(ordinary, ((0, 0, 6, 7), (0, 0, 5, 5))),
             success='马跳过了前排棋子。进入时空后，2＋1 的形状仍然成立。',
             quiz=_quiz('车、象、后可以像马一样穿过挡路棋子吗？', ['可以，只要落点空着', '不可以，滑动路径必须畅通'], 1, '跨棋盘的滑动路径也不能被棋子或不存在的中间棋盘隔断。')),
        dict(id='many-moves', title='红框不止一张时', stage='基础操作',
             description='这里有两张必须推进的棋盘。在 L0 把 e2 兵走到 e4，再在 L+1 把 e2 兵走到 e4。观察需推进数量从 2 → 1 → 0。',
             points=['走完第一张后，白方还不能提交；另一张红框仍需推进。', '同一行动可从不同棋盘走子。不是把同一条线上刚走完的棋子连走两次。'],
             plans=practice(two_pawns, ((0, 0, 4, 6), (0, 0, 4, 4)), ((1, 0, 4, 6), (1, 0, 4, 4))),
             success='两次走子，一次提交。红框随局面重新计算，要一直看到没有待推进棋盘。',
             quiz=_quiz('第一张棋盘走完，第二张还有红框，应该怎么办？', ['继续推进第二张，再检查能否提交', '直接等待对手', '在第一张新棋盘再走一次白棋'], 0, '一次行动要完成当前必须推进的棋盘；不要只盯着刚走过的那一张。')),
        dict(id='cross-board', title='车跨到另一条线', stage='时空移动',
             description='车沿一个方向走。这里仅改变时间线 L：从 L0 的 d4 移到 L+1 的 d4，格子和时间不变。',
             points=['这里的目标是另一条线的最新白方棋盘，所以两条线各产生一个后继：一张车离开，一张车到达。',
                     '这次一手同时推进两张红框棋盘。跨线不一定产生新支线，落到历史才会分支。'],
             plans=practice(crossing, ((0, 0, 3, 4), (1, 0, 3, 4))),
             success='L0 后继没有这枚车，L+1 后继多了这枚车。原先两张棋盘成为历史。',
             quiz=_quiz('这次跨到另一条线的最新棋盘，会发生什么？', ['两张棋盘各产生后继，不额外创建支线', '删掉出发时间线', '必定再创建第三条时间线'], 0, '“跨线”和“生成分支”是两件事，关键看目标是不是历史。')),
        dict(id='history', title='回到过去，生成分支', stage='时空移动',
             description='让白车从 L0 · T1 白方的 d4，回到 L0 · T0 白方的 d4。只改变时间 T，符合车的走法。',
             points=['跨时间的目标必须是同色阶段：白方阶段的棋子不能直接落到黑方阶段。',
                     '历史不会被覆盖。以目标历史为起点，新建一条线并生成走子后的棋盘；车真正到达的是新支线的后继。',
                     '原线的后续发展仍在，新线从过去另走一种发展。白方建 L+1、L+2…，黑方建 L−1、L−2…。'],
             plans=practice(branching, ((0, 2, 3, 4), (0, 0, 3, 4))),
             success='车到达新分支 L+1；L0 · T0 的原历史没有车，也没有被改写。分支可能把当前时刻拉回过去。',
             quiz=_quiz('回到历史后，原来已经发生的棋局会被抹掉吗？', ['会，所有后续棋盘都消失', '不会，原历史保留，另外产生分支'], 1, '时间旅行增加一种发展，不是撤销旧棋局。请跟随到达高亮和分支连线查看结果。')),
        dict(id='bishop', title='象的斜线也能跨棋盘', stage='时空移动',
             description='让象从 L0 的 d4 到 L+1 的 e4：时间线加一，棋盘内向右一格。这是两个方向各走一步的“斜线”。',
             points=['象不一定要在单张棋盘上斜走；它要的是两个方向等距变化。', '例如回到前一个 T，同时横移一格，也可能是象的方向；仍需目标棋盘存在、阶段相同、路径畅通。',
                     '后可同时改变一至四个方向且距离相同，王走这些方向的一步。能否安全提交还要另看王安全。'],
             plans=practice(_engine(_position(0, 0, {(3, 4): 'B'}), _position(1, 0)), ((0, 0, 3, 4), (1, 0, 4, 4))),
             success='格子横坐标与时间线各改变一步，象的走法仍然成立。',
             quiz=_quiz('象从 L0 的 d4 到 L+1 的 d4，只改变时间线，符合走法吗？', ['符合，象可以任意跨线', '不符合，象恰好需要两个方向等距变化'], 1, '只改变一个方向是车的形状；象必须同时改变两个方向。')),
        dict(id='knight', title='马的 2＋1 延伸到时空', stage='时空移动',
             description='让马从 L0 的 d4 到 L+1 的 f4：棋盘内横走两格，时间线走一步。',
             points=['也可以把时间当成两个方向中的一个。马跳跃时不检查中间格，但落点棋盘必须存在、阶段相同，且不能是己方棋子。',
                     '不是所有棋子跳到其他棋盘时都保持原格子。目标位置由该棋子的多维走法决定。正式对局会显示该棋子的所有合法落点。'],
             plans=practice(_engine(_position(0, 0, {(3, 4): 'N'}), _position(1, 0)), ((0, 0, 3, 4), (1, 0, 5, 4))),
             success='这次跨线后，马的格子位置也变了。判断跳跃时要一起看格子、T 和 L。',
             quiz=_quiz('马可以跳到任意一张不存在的棋盘吗？', ['可以，马能跳跃', '不可以，跳跃免查中间路径，但目标棋盘必须存在'], 1, '跳跃并不凭空创建目标棋盘；只有落到已有历史才会由引擎生成分支。')),
        dict(id='pawn', title='兵：前进与吃子不同', stage='时空移动',
             description='用 e4 白兵吃掉 d5 黑兵。兵直走时不能吃子；在本棋盘上，吃子要斜前方一格。',
             points=['白兵朝第 8 排前进，黑兵朝第 1 排前进；翻转视角不会改变方向。',
                     '时空中的直行沿 L：白方向编号更小的线，黑方向编号更大的线，保持格子与 T 不变。不是随意回到过去。',
                     '时空吃子保持格子不变，同时改变 T 一步、沿本方前进方向改变 L 一步。不能把格子横移和时间变化任意拼起来。',
                     '未移动的兵可沿前进方向走两步，途中必须畅通；跨线双步也需要中间棋盘存在。'],
             plans=practice(_engine(_position(0, 0, {(4, 4): 'P', (3, 3): 'p'})), ((0, 0, 4, 4), (0, 0, 3, 3))),
             success='黑兵已被吃掉，白兵在 d5。兵的跨线前进与跨时空吃子同样要分开记。',
             quiz=_quiz('白兵沿时间线前进的方向是？', ['朝更大的 L', '朝更小的 L', '两个方向都能随便走'], 1, '白兵向更小的 L，黑兵向更大的 L。这与白方创建正编号支线不是同一个概念。')),
        dict(id='present', title='找对“当前时刻”', stage='准备实战',
             description='这里 L0 已走到 T2，L+1 还在 T1，L+2 停在 T0 但属于非活动线。先找红框，而不是最右边或编号最大的棋盘。',
             points=['当前时刻取所有活动线最新棋盘中最早的阶段；非活动线暂不参与这个计算。',
                     '所以这里必须推进 L+1。L0 的白方棋盘在更晚时间，是可选走子；L+2 也是可选，不能把它误当成历史或已删除。',
                     '一方比另一方多出的第二条及以后支线暂不活动；对手新增支线可能让它们重新活动。每走一手后重新看红框。'],
             snapshot=serialize(present),
             quiz=_quiz('这三张棋盘中，白方现在必须推进哪一张？', ['最右边的 L0 · T2', '红框的 L+1 · T1', '最早的 L+2 · T0 非活动线'], 1, 'L+1 是活动线中时间最早的最新棋盘；L+2 非活动，不决定当前时刻。')),
        dict(id='king-safety', title='没有红框也可能不能提交', stage='准备实战',
             description='下面演示一个不能提交的局面：虽然没有红框，但黑车沿第一排威胁白王。仅推进时间还不够。',
             points=['提交时所有己方王都必须安全，包括其他时间线、同一棋盘上的多个王，以及仍可被攻击的历史王。',
                     '攻击也能跨时间、跨线。看到王安全提示，应检查攻击来源与目标，调整当前行动；不能只看眼前最新的王。',
                     '对手将军时，你的完整行动必须解除威胁。若没有任何完整合法行动且被将军，就是将死；未被将军则是逼和。',
                     '正式对局不能提交时：先查剩余红框，再查王安全，最后确认是否轮到自己以及对局是否已经结束。'],
             snapshot=serialize(unsafe),
             quiz=_quiz('红框为零，但王仍会被攻击，能提交吗？', ['能，红框清空就是完成了', '不能，还必须满足全部王的安全'], 1, '红框清空和王安全是两项条件，缺一不可。看行动面板的具体原因。')),
        dict(id='challenge', title='独立完成一个行动', stage='准备实战',
             description='现在撤掉指定走法：请自行推进两张红框棋盘，再提交。每张棋盘只练习白兵，可以前进一格或两格，顺序由你决定。',
             points=['先看行动方与红框 → 选白兵 → 观察蓝色合法落点 → 走子后重新看红框 → 安全后提交。',
                     '没有自动亮出的出发点。不确定时可点“给我提示”；走错练习选择可“撤回练习一步”，都不影响真实对局。'],
             independent=True, plans=[],
             success='你已独立完成多棋盘行动。开一局简单人机时，先在主线正常发展棋子，再尝试一次有明确目的的时间旅行。',
             quiz=_quiz('正式对局中，落下棋子后下一步应该看什么？', ['只看棋子有没有到最右边', '重新检查红框、王安全和提交状态'], 1, '能看懂棋盘、判断必须推进的对象、选择落点并安全提交，就能开始实战。遇到陌生走法可随时重开教程。')),
    ]
    # Both move orders and both distances, generated without live-game mutation.
    for order in permutations((0, 1)):
        for ranks in product((5, 4), repeat=2):
            moves = [((lane, 0, 4, 6), (lane, 0, 4, rank)) for lane, rank in zip(order, ranks)]
            lessons[-1]['plans'].append(_plan(two_pawns, moves, serialize, move_payload))
    return lessons
