"""学习特化数据模型定义。

实体关系：
    User (ktem) ──< LearningProject ──< KnowledgeNode >── KnowledgeEdge
                          │                  │
                          │                  ├──< ProgressRecord (掌握度时序)
                          │                  ├──< Card ──< ReviewLog (FSRS)
                          │                  ├──< Quiz ──< QuizQuestion
                          │                  │              └──< QuizAttempt
                          │                  └──< Task (实操/环境)
                          └──< DailyReport
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class LearningProject(SQLModel, table=True):
    """学习项目 (一次选题对应一个项目)"""

    __tablename__ = "le_project"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, description="关联 ktem User.id")
    title: str = Field(default="", description="选题标题，如 '从零学 Transformer'")
    topic: str = Field(description="原始选题描述")
    background: str = Field(default="", description="学习者背景")
    goal: str = Field(default="", description="学习目标")
    weekly_hours: float = Field(default=10.0, description="每周可投入小时数")
    # 路线原始 JSON (知识 DAG 的完整结构，含阶段、依赖、估时)
    roadmap_json: str = Field(default="{}", description="AI 生成的学习路线 JSON")
    course_blueprint_json: str = Field(
        default="{}", description="V2 课程-单元-讲次-课节层级蓝图"
    )
    status: str = Field(
        default="active", description="active|paused|completed|archived"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CourseDraft(SQLModel, table=True):
    """V2 课程创作草稿。"""

    __tablename__ = "le_course_draft"

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: str = Field(default="default", index=True)
    input_text: str = Field(default="")
    material_text: str = Field(default="")
    material_name: str = Field(default="")
    status: str = Field(default="researching", index=True)
    revision: int = Field(default=1)
    research_json: str = Field(default="{}")
    questionnaire_json: str = Field(default="{}")
    answers_json: str = Field(default="{}")
    blueprint_json: str = Field(default="{}")
    preview_json: str = Field(default="{}")
    published_project_id: Optional[int] = Field(
        default=None, foreign_key="le_project.id", index=True
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CourseSource(SQLModel, table=True):
    """调研阶段使用的教材或网络来源。"""

    __tablename__ = "le_course_source"

    id: Optional[int] = Field(default=None, primary_key=True)
    draft_id: int = Field(foreign_key="le_course_draft.id", index=True)
    owner_id: str = Field(default="default", index=True)
    source_type: str = Field(default="web", description="material|web")
    title: str = Field(default="")
    url: str = Field(default="")
    locator: str = Field(default="")
    excerpt: str = Field(default="")
    read_status: str = Field(default="summary", description="full|summary|failed")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LessonContentRevision(SQLModel, table=True):
    """正式课程课节正文的当前版本及生成状态。"""

    __tablename__ = "le_lesson_content"

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: str = Field(default="default", index=True)
    project_id: int = Field(foreign_key="le_project.id", index=True)
    node_id: int = Field(foreign_key="le_knode.id", unique=True, index=True)
    revision: int = Field(default=1)
    status: str = Field(default="ready", description="pending|generating|ready|failed")
    content: str = Field(default="")
    input_hash: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class KnowledgeNode(SQLModel, table=True):
    """知识图谱节点 (DAG 中的一个知识点)"""

    __tablename__ = "le_knode"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="le_project.id", index=True)
    code: str = Field(description="节点编号，如 '1.2.3'")
    title: str = Field(description="知识点标题")
    description: str = Field(default="", description="知识点详细说明")
    stage: str = Field(default="base", description="base|strengthen|sprint 阶段")
    # 估时 (小时)、难度 (1-5)、掌握度 (0.0-1.0)
    est_hours: float = Field(default=2.0)
    difficulty: int = Field(default=3)
    mastery: float = Field(default=0.0, description="综合掌握度")
    # 状态机：pending|learning|reviewing|mastered|weak
    status: str = Field(default="pending")
    # 可选关联到 Kotaemon 的资料集合 (用于 RAG 对话聚焦)
    collection_ids: str = Field(
        default="", description="逗号分隔的 Kotaemon collection id"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class KnowledgeEdge(SQLModel, table=True):
    """知识图谱边 (依赖关系)：source 依赖 target (先学 target)"""

    __tablename__ = "le_kedge"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="le_project.id", index=True)
    source_id: int = Field(foreign_key="le_knode.id", description="当前节点")
    target_id: int = Field(foreign_key="le_knode.id", description="前置依赖节点")
    relation: str = Field(
        default="prerequisite", description="prerequisite|related|extends"
    )


class Card(SQLModel, table=True):
    """FSRS 复习卡片"""

    __tablename__ = "le_card"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    node_id: Optional[int] = Field(default=None, foreign_key="le_knode.id", index=True)
    project_id: Optional[int] = Field(
        default=None, foreign_key="le_project.id", index=True
    )
    # 卡片内容
    front: str = Field(description="正面 (问题/提示)")
    back: str = Field(description="背面 (答案/要点)")
    card_type: str = Field(default="basic", description="basic|cloze|concept")
    # FSRS v6 参数 (由 fsrs 库维护，这里冗余存储便于查询)
    stability: float = Field(default=0.0)
    difficulty: float = Field(default=0.0)
    last_review: Optional[datetime] = Field(default=None)
    next_review: datetime = Field(default_factory=datetime.utcnow)
    reps: int = Field(default=0, description="累计复习次数 (本系统维护，非 fsrs 字段)")
    step: int = Field(default=0, description="FSRS 学习/重学阶段内的步进")
    state: int = Field(
        default=0, description="0=new(本系统) 1=Learning 2=Review 3=Relearning"
    )
    due_order: int = Field(default=0, description="同日到期排序")
    suspended: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReviewLog(SQLModel, table=True):
    """复习记录 (FSRS review log)"""

    __tablename__ = "le_reviewlog"

    id: Optional[int] = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="le_card.id", index=True)
    user_id: str = Field(index=True)
    rating: int = Field(description="FSRS 评分 1again 2hard 3good 4easy")
    state: int = Field(description="复习前 state")
    stability: float = Field(description="复习后 stability")
    difficulty: float = Field(description="复习后 difficulty")
    reviewed_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    # 一次「展示→评分」对应一个 request_id; 网络重试/双击命中唯一索引, 不会重复调度
    request_id: Optional[str] = Field(
        default=None, unique=True, index=True, description="提交去重 ID"
    )


class Quiz(SQLModel, table=True):
    """一次测验"""

    __tablename__ = "le_quiz"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(
        default=None, foreign_key="le_project.id", index=True
    )
    user_id: str = Field(index=True)
    node_id: Optional[int] = Field(default=None, foreign_key="le_knode.id")
    title: str = Field(default="")
    quiz_type: str = Field(
        default="mixed", description="choice|fill|short|practice|mixed"
    )
    # 出题范围：weak 节点 id 列表 / 全部
    scope_node_ids: str = Field(default="", description="逗号分隔")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class QuizQuestion(SQLModel, table=True):
    """测验题目"""

    __tablename__ = "le_quiz_question"

    id: Optional[int] = Field(default=None, primary_key=True)
    quiz_id: int = Field(foreign_key="le_quiz.id", index=True)
    node_id: Optional[int] = Field(default=None, foreign_key="le_knode.id")
    qtype: str = Field(description="choice|fill|short|practice")
    stem: str = Field(description="题干")
    options: str = Field(default="", description="选项 JSON (选择题)")
    answer: str = Field(description="标准答案")
    explanation: str = Field(default="", description="解析")
    difficulty: int = Field(default=3)


class QuizAttempt(SQLModel, table=True):
    """答题记录"""

    __tablename__ = "le_quiz_attempt"

    id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="le_quiz_question.id", index=True)
    user_id: str = Field(index=True)
    user_answer: str = Field(default="")
    is_correct: Optional[bool] = Field(default=None, description="由得分与题型阈值判定")
    score: float = Field(default=0.0, description="部分得分 0.0-1.0")
    error_type: str = Field(
        default="",
        description="concept_unclear|detail_missed|incomplete|procedural_error|blank",
    )
    feedback: str = Field(default="", description="批改反馈")
    attempted_at: datetime = Field(default_factory=datetime.utcnow)
    # 一次「展示→提交」对应一个 request_id; 网络重试/双击命中唯一索引, 不会重复计分
    request_id: Optional[str] = Field(
        default=None, unique=True, index=True, description="提交去重 ID"
    )


class ProgressRecord(SQLModel, table=True):
    """掌握度时序记录 (用于绘制学习曲线/热力图)"""

    __tablename__ = "le_progress"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    project_id: int = Field(foreign_key="le_project.id", index=True)
    node_id: Optional[int] = Field(default=None, foreign_key="le_knode.id")
    metric: str = Field(description="mastery|study_minutes|cards_reviewed|quiz_score")
    value: float = Field(default=0.0)
    recorded_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class Task(SQLModel, table=True):
    """实操/环境任务"""

    __tablename__ = "le_task"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="le_project.id", index=True)
    node_id: Optional[int] = Field(default=None, foreign_key="le_knode.id")
    title: str = Field(description="任务标题")
    description: str = Field(default="", description="任务说明 (含命令/步骤)")
    task_type: str = Field(default="practice", description="env|practice|project")
    status: str = Field(default="pending", description="pending|doing|done|blocked")
    output: str = Field(default="", description="完成记录/产出链接")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DailyReport(SQLModel, table=True):
    """学习日报"""

    __tablename__ = "le_daily_report"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    project_id: Optional[int] = Field(default=None, foreign_key="le_project.id")
    report_date: datetime = Field(index=True)
    content: str = Field(description="AI 生成的日报 markdown")
    study_minutes: int = Field(default=0)
    cards_reviewed: int = Field(default=0)
    nodes_progressed: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NodeNote(SQLModel, table=True):
    """知识点的学习笔记 (用户手写, 区别于 AI 生成的教学内容)"""

    __tablename__ = "le_note"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(default="default", index=True)
    node_id: int = Field(foreign_key="le_knode.id", index=True)
    project_id: int = Field(foreign_key="le_project.id", index=True)
    content: str = Field(default="", description="用户的笔记 markdown")
    selection: str = Field(default="", description="触发笔记的选词 (可选)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class NodeResource(SQLModel, table=True):
    """知识点的参考资料 (AI 推荐 + 用户补充)"""

    __tablename__ = "le_resource"

    id: Optional[int] = Field(default=None, primary_key=True)
    node_id: int = Field(foreign_key="le_knode.id", index=True)
    project_id: int = Field(foreign_key="le_project.id", index=True)
    title: str = Field(default="", description="资料标题")
    url: str = Field(default="", description="链接")
    rtype: str = Field(default="doc", description="doc|video|book|article|tool|search")
    description: str = Field(default="", description="推荐理由/内容摘要")
    preview: str = Field(default="", description="预览内容 (抓取的正文或摘要)")
    source: str = Field(default="ai", description="ai|user")
    created_at: datetime = Field(default_factory=datetime.utcnow)
