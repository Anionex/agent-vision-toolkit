import { useEffect, useRef, useState } from 'react'
import {
  ArrowRight,
  Bot,
  Captions,
  Check,
  CheckCircle2,
  Code2,
  Copy,
  Crop,
  Crosshair,
  Eye,
  FileSearch,
  Focus,
  GitFork,
  Image as ImageIcon,
  Layers3,
  Menu,
  MessageSquareText,
  MousePointer2,
  Network,
  PanelTop,
  PlugZap,
  Radar,
  ScanLine,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Terminal,
  Waypoints,
  Workflow,
  X,
  Zap,
} from 'lucide-react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import CapabilityChart from './components/CapabilityChart.jsx'
import './App.css'

const repoUrl = 'https://github.com/Anionex/agent-vision-toolkit'
const installCommand =
  'npx skills add Anionex/agent-vision-toolkit --skill vision-tools -a codex -g --copy -y'
const landingAsset = (file) => `${import.meta.env.BASE_URL}landing/${file}`

const platforms = ['Codex', 'Claude Code', 'Pi', 'Oh My Pi', 'OpenCode']

const tools = [
  {
    id: 'glance',
    icon: Eye,
    question: '图里是什么？',
    description: '理解画面、读取文字、围绕当前问题追问。',
    command: 'glance image.png -q "..."',
  },
  {
    id: 'ground',
    icon: Crosshair,
    question: '目标在哪里？',
    description: '定位一个可命名目标，返回原图像素坐标。',
    command: 'ground shot.png "Send button"',
  },
  {
    id: 'detect',
    icon: ScanSearch,
    question: '这里都有什么？',
    description: '清点一类或全部元素，建立可操作的视觉目录。',
    command: 'detect page.png "buttons"',
  },
  {
    id: 'trace',
    icon: ScanLine,
    question: '精确形状是什么？',
    description: '从真实像素提取 SVG 几何，不靠模型猜数字。',
    command: 'trace icon.png -o icon.svg',
  },
  {
    id: 'crop',
    icon: Crop,
    question: '把这块单独取出？',
    description: '裁出区域，供放大、复查、提取与复用。',
    command: 'crop shot.png --region x1,y1,x2,y2',
  },
]

const scenarios = [
  {
    id: 'qa',
    label: '图像问答',
    shortLabel: '问答',
    icon: MessageSquareText,
    eyebrow: 'SEE & ASK',
    title: '不止“描述图片”，而是回答正在问的问题',
    description:
      '把当前意图带进视觉请求；需要更多细节时，围绕原图继续追问，而不是重新猜测上下文。',
    image: landingAsset('effect-3.jpg'),
    imageAlt: '在编码助手中围绕同一张图片进行多轮问答的实际效果',
    imagePosition: 'center 40%',
    tools: ['glance'],
    tags: ['多轮追问', '文字转写', '局部放大'],
  },
  {
    id: 'ocr',
    label: '长截图 OCR',
    shortLabel: '长 OCR',
    icon: Captions,
    eyebrow: 'READ IN ORDER',
    title: '安全切分长页面，再按顺序合并内容',
    description:
      '找到低内容切分带，逐块 OCR，消除重叠，并对聊天记录的说话人、时间戳与边界做专门校验。',
    tools: ['glance', 'crop'],
    tags: ['边界审计', '断点续跑', '聊天结构'],
    customPreview: 'ocr',
  },
  {
    id: 'ui',
    label: '前端 UI 还原',
    shortLabel: 'UI 还原',
    icon: PanelTop,
    eyebrow: 'REBUILD & VERIFY',
    title: '从截图理解布局，再用真实渲染反复校准',
    description:
      '先复用组件与资产，再组合语义 HTML、CSS、提取素材和像素级复查，把“看起来像”推进到“可以交付”。',
    image: landingAsset('ui-restore-result.png'),
    imageAlt: '由手绘参考图还原出的 JupyterLab 工作区界面',
    imagePosition: 'center',
    tools: ['glance', 'ground', 'detect', 'trace', 'crop'],
    tags: ['组件复用', '视觉对齐', '截图验收'],
  },
  {
    id: 'gui',
    label: 'GUI 自动化',
    shortLabel: 'GUI',
    icon: MousePointer2,
    eyebrow: 'LOCATE & ACT',
    title: '每一步都先看清，再操作，再验证新状态',
    description:
      '把截图变成位置和状态信息，让文本模型能找到控件、执行单步动作，并根据下一张截图闭环。',
    image: landingAsset('effect-4.jpg'),
    imageAlt: '文本模型通过视觉定位工具自主操作棋盘界面',
    imagePosition: 'center',
    tools: ['glance', 'ground', 'detect'],
    tags: ['控件定位', '单步验证', '状态闭环'],
  },
  {
    id: 'structure',
    label: '图形与结构还原',
    shortLabel: '图形',
    icon: Layers3,
    eyebrow: 'TRACE & RECREATE',
    title: '从像素中恢复可编辑的图形、结构与页面',
    description:
      '识别节点和层级，必要时提取前景或追踪精确轮廓，输出可维护的 SVG、HTML、Mermaid 或其他结构化结果。',
    image: landingAsset('infographic-restore-result.png'),
    imageAlt: '由参考截图重建的可编辑信息图页面',
    imagePosition: 'center',
    tools: ['glance', 'ground', 'trace', 'crop'],
    tags: ['SVG 几何', '结构化输出', '透明素材'],
  },
]

const visionPrinciples = [
  {
    icon: Focus,
    number: '01',
    title: '有意图地看',
    description:
      '把“为什么要看这张图”作为 focus hint 传给视觉模型，让第一轮描述就围绕当前任务组织。',
  },
  {
    icon: Radar,
    number: '02',
    title: '从全局到局部',
    description:
      '首轮描述是地图；重要细节通过定位、裁切、放大和二次提问逐层收敛。',
  },
  {
    icon: ShieldCheck,
    number: '03',
    title: '用工具验证',
    description:
      '语义交给视觉模型，颜色、坐标、轮廓和差异交给确定性工具，避免把猜测当事实。',
  },
]

function BrandMark({ compact = false }) {
  return (
    <span className={`brand-mark ${compact ? 'brand-mark--compact' : ''}`}>
      <Eye aria-hidden="true" />
      <span className="brand-mark__dot" />
    </span>
  )
}

function SectionHeading({ eyebrow, title, description, align = 'left' }) {
  return (
    <div className={`section-heading section-heading--${align} reveal`}>
      <p className="eyebrow">
        <span />
        {eyebrow}
      </p>
      <h2>{title}</h2>
      {description ? <p className="section-description">{description}</p> : null}
    </div>
  )
}

function FlowNode({ icon: Icon, title, meta, accent = false }) {
  return (
    <div className={`flow-node ${accent ? 'flow-node--accent' : ''}`}>
      <span className="flow-node__icon">
        <Icon aria-hidden="true" />
      </span>
      <strong>{title}</strong>
      <span>{meta}</span>
    </div>
  )
}

function FlowConnector({ label, muted = false }) {
  return (
    <div className={`flow-connector ${muted ? 'flow-connector--muted' : ''}`}>
      {label ? <span className="flow-connector__label">{label}</span> : null}
      <span className="flow-connector__line">
        <span className="flow-connector__dot" />
        <ArrowRight aria-hidden="true" />
      </span>
    </div>
  )
}

function ScenarioPreview({ scenario }) {
  if (scenario.customPreview === 'ocr') {
    return (
      <div className="ocr-preview" aria-label="长截图切分与 OCR 流程示意">
        <div className="ocr-preview__rail">
          <span className="ocr-preview__rail-dot ocr-preview__rail-dot--active" />
          <span className="ocr-preview__rail-line" />
          <span className="ocr-preview__rail-dot" />
          <span className="ocr-preview__rail-line" />
          <span className="ocr-preview__rail-dot" />
        </div>
        <div className="ocr-preview__phone">
          <div className="ocr-preview__topbar">
            <span />
            <strong>long-chat.png</strong>
            <span />
          </div>
          <div className="ocr-preview__messages">
            <div className="chat-bubble chat-bubble--left">
              <span className="chat-bubble__name">Alex · 09:41</span>
              <span>Can the agent keep the message order?</span>
            </div>
            <div className="chat-bubble chat-bubble--right">
              <span className="chat-bubble__name">Vision toolkit · 09:42</span>
              <span>Split at safe bands, OCR each chunk, then audit boundaries.</span>
            </div>
            <div className="ocr-cut">
              <span>SAFE CUT BAND</span>
            </div>
            <div className="chat-bubble chat-bubble--left chat-bubble--short">
              <span className="chat-bubble__name">Alex · 09:43</span>
              <span>And the overlap?</span>
            </div>
            <div className="chat-bubble chat-bubble--right">
              <span>Only duplicated overlap is merged.</span>
            </div>
          </div>
        </div>
        <div className="ocr-preview__result">
          <span className="preview-chip preview-chip--success">
            <CheckCircle2 aria-hidden="true" /> 3 chunks verified
          </span>
          <div className="ocr-preview__document">
            <span className="document-line document-line--strong" />
            <span className="document-line" />
            <span className="document-line document-line--medium" />
            <span className="document-line" />
            <span className="document-line document-line--short" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <img
      className="scenario-preview__image"
      src={scenario.image}
      alt={scenario.imageAlt}
      style={{ objectPosition: scenario.imagePosition }}
      loading="lazy"
    />
  )
}

function App() {
  const rootRef = useRef(null)
  const scenarioPreviewRef = useRef(null)
  const copyTimerRef = useRef(null)
  const [activeScenario, setActiveScenario] = useState(2)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger)
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined

    const context = gsap.context(() => {
      const intro = gsap.timeline({ defaults: { ease: 'power3.out' } })
      intro
        .from('.site-nav', { y: -18, autoAlpha: 0, duration: 0.65 })
        .from('.hero-copy > *', { y: 24, autoAlpha: 0, duration: 0.65, stagger: 0.08 }, '-=0.28')
        .from('.hero-visual', { y: 28, scale: 0.97, autoAlpha: 0, duration: 0.9 }, '-=0.72')
        .from('.platform-strip__inner > *', { y: 10, autoAlpha: 0, duration: 0.45, stagger: 0.05 }, '-=0.36')

      gsap.to('.float-card--focus', { y: -8, duration: 2.8, repeat: -1, yoyo: true, ease: 'sine.inOut' })
      gsap.to('.float-card--tools', { y: 7, duration: 3.2, repeat: -1, yoyo: true, ease: 'sine.inOut' })
      gsap.to('.focus-orbit', { rotation: 360, duration: 22, repeat: -1, ease: 'none', transformOrigin: 'center' })

      gsap.utils.toArray('.reveal').forEach((element) => {
        gsap.from(element, {
          scrollTrigger: { trigger: element, start: 'top 88%', once: true },
          y: 24,
          autoAlpha: 0,
          duration: 0.72,
          ease: 'power3.out',
        })
      })

      gsap.utils.toArray('.flow-connector__dot').forEach((dot, index) => {
        gsap.fromTo(dot, { x: 0, autoAlpha: 0 }, {
          x: () => Math.max(dot.parentElement.clientWidth - 20, 12),
          autoAlpha: 1,
          duration: 1.45,
          delay: index * 0.18,
          repeat: -1,
          repeatDelay: 0.5,
          repeatRefresh: true,
          ease: 'power1.inOut',
        })
      })
    }, rootRef)

    return () => context.revert()
  }, [])

  useEffect(() => {
    const element = scenarioPreviewRef.current
    if (!element || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined
    const tween = gsap.fromTo(element, { y: 12, autoAlpha: 0.45 }, { y: 0, autoAlpha: 1, duration: 0.48, ease: 'power2.out' })
    return () => tween.kill()
  }, [activeScenario])

  useEffect(() => () => {
    if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current)
  }, [])

  const copyInstallCommand = async () => {
    await navigator.clipboard.writeText(installCommand)
    setCopied(true)
    if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current)
    copyTimerRef.current = window.setTimeout(() => setCopied(false), 1800)
  }

  const active = scenarios[activeScenario]

  return (
    <div className="site-shell" ref={rootRef}>
      <header className="site-header">
        <nav className="site-nav page-width" aria-label="主导航">
          <a className="brand" href="#top" aria-label="agent-vision-toolkit 首页"><BrandMark compact /><span>agent-vision-toolkit</span></a>
          <button className="mobile-menu-button" type="button" aria-label={mobileOpen ? '关闭导航菜单' : '打开导航菜单'} aria-expanded={mobileOpen} onClick={() => setMobileOpen((open) => !open)}>
            {mobileOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
          </button>
          <div className={`nav-links ${mobileOpen ? 'nav-links--open' : ''}`}>
            <a href="#vision" onClick={() => setMobileOpen(false)}>Vision</a>
            <a href="#how-it-works" onClick={() => setMobileOpen(false)}>原理</a>
            <a href="#scenarios" onClick={() => setMobileOpen(false)}>场景</a>
            <a href="#tools" onClick={() => setMobileOpen(false)}>工具</a>
          </div>
          <a className="nav-cta" href={repoUrl} target="_blank" rel="noreferrer"><GitFork aria-hidden="true" />GitHub</a>
        </nav>
      </header>

      <main id="top">
        <section className="hero-section">
          <div className="hero-grid page-width">
            <div className="hero-copy">
              <div className="hero-kicker"><span className="hero-kicker__pulse" />Vision layer for text-only agents</div>
              <h1>让纯文本 Agent<span>真正看见</span>，并且知道该看哪里。</h1>
              <p className="hero-lead">一套可组合、可验证的视觉工具与接入层：理解图片、读取长截图、定位界面、还原前端、操作 GUI，覆盖从“看见”到“完成任务”的整个闭环。</p>
              <div className="hero-actions">
                <a className="button button--primary" href="#scenarios">探索应用场景<ArrowRight aria-hidden="true" /></a>
                <a className="button button--secondary" href={repoUrl} target="_blank" rel="noreferrer"><GitFork aria-hidden="true" />查看源码</a>
              </div>
              <div className="hero-proof">
                <div className="hero-proof__item"><span><Check aria-hidden="true" /></span><div><strong>Intent-aware</strong><small>把查看意图传给视觉模型</small></div></div>
                <div className="hero-proof__item"><span><Check aria-hidden="true" /></span><div><strong>Tool-equipped</strong><small>语义理解 + 像素级验证</small></div></div>
              </div>
            </div>

            <div className="hero-visual" aria-label="项目蓝白机器人与视觉工具箱插画">
              <div className="hero-visual__glow" />
              <img className="hero-visual__image" src={landingAsset('hero.png')} alt="蓝白机器人查看技能清单，旁边是视觉工具箱和摄像头机器人" />
              <div className="focus-orbit" aria-hidden="true"><span /><span /><span /></div>
              <div className="float-card float-card--focus"><span className="float-card__icon"><Focus aria-hidden="true" /></span><div><small>FOCUS HINT</small><strong>Keep the task in view</strong></div></div>
              <div className="float-card float-card--tools"><span className="float-card__icon float-card__icon--soft"><Waypoints aria-hidden="true" /></span><div><small>VISUAL TOOLKIT</small><strong>5 focused tools</strong></div></div>
              <div className="hero-status"><span className="hero-status__dot" />Vision channel ready</div>
            </div>
          </div>
          <div className="platform-strip"><div className="platform-strip__inner page-width"><span className="platform-strip__label">Seamless with</span>{platforms.map((platform) => <span className="platform-badge" key={platform}><Bot aria-hidden="true" />{platform}</span>)}</div></div>
        </section>

        <section className="section vision-section" id="vision">
          <div className="page-width">
            <div className="vision-intro">
              <SectionHeading eyebrow="OUR VISION" title="视觉不该只是模型的天赋，而应该是 Agent 可调用的能力。" description="把视觉拆成清晰的问题、专门的工具和可验证的步骤。这样，纯文本模型也能在真实工作流中稳定地理解、定位、重建和操作。" />
              <div className="vision-statement reveal"><Sparkles aria-hidden="true" /><p>What it thinks is what it sees.<span>让输入画面与 Agent 的思考始终处在同一个任务语境里。</span></p></div>
            </div>
            <div className="principle-card-grid">
              {visionPrinciples.map(({ icon: Icon, number, title, description }) => <article className="principle-card reveal" key={number}><div className="principle-card__topline"><span className="principle-card__icon"><Icon aria-hidden="true" /></span><span className="principle-card__number">{number}</span></div><h3>{title}</h3><p>{description}</p></article>)}
            </div>
          </div>
        </section>

        <section className="section how-section" id="how-it-works">
          <div className="page-width">
            <SectionHeading eyebrow="HOW IT WORKS" title="不是再加一层泛化描述，而是保留 Agent 的查看意图。" description="同一张图，在不同任务里真正重要的细节并不相同。Focus hint 只告诉视觉模型当前要关注什么，不添加任何新的视觉事实。" align="center" />
            <div className="flow-comparison reveal">
              <article className="flow-lane flow-lane--generic">
                <div className="flow-lane__header"><div><span className="flow-lane__status" />Generic bridge</div><span>固定提示词</span></div>
                <div className="flow-track"><FlowNode icon={Bot} title="Text Agent" meta="task intent" /><FlowConnector label="generic prompt" muted /><FlowNode icon={Eye} title="Vision Model" meta="sees image" /><FlowConnector muted /><FlowNode icon={FileSearch} title="Description" meta="broad summary" /></div>
                <div className="flow-output flow-output--generic"><span>结果</span><p>“一个带侧边栏、卡片、按钮和文本的软件界面。”</p><small>画面没有错，但任务真正需要的布局、间距和组件关系被稀释了。</small></div>
              </article>
              <article className="flow-lane flow-lane--aware">
                <div className="flow-lane__header"><div><span className="flow-lane__status" />Task-aware vision</div><span>Focus hint</span></div>
                <div className="focus-hint-bubble"><Focus aria-hidden="true" /><div><small>WHY THE AGENT IS LOOKING</small><strong>“Recreate this UI as an HTML page.”</strong></div></div>
                <div className="flow-track flow-track--aware"><FlowNode icon={Bot} title="Text Agent" meta="task intent" /><FlowConnector label="intent travels" /><FlowNode icon={Eye} title="Vision Model" meta="image + focus" accent /><FlowConnector /><FlowNode icon={Workflow} title="Useful Context" meta="task-ready" accent /></div>
                <div className="flow-output flow-output--aware"><span>返回与任务相关的视觉上下文</span><div className="output-chips">{['Layout', 'Components', 'Spacing', 'Colors', 'Hierarchy', 'Text styles'].map((item) => <span key={item}><CheckCircle2 aria-hidden="true" />{item}</span>)}</div></div>
              </article>
            </div>
            <a className="principle-figure reveal" href={landingAsset('focus-hint-comparison-1.png')} target="_blank" rel="noreferrer"><div className="principle-figure__image-wrap"><img src={landingAsset('focus-hint-comparison-1.png')} alt="传统 image-to-text 与 task-aware focus hint 方案的完整对比图" loading="lazy" /></div><div className="principle-figure__caption"><span><ImageIcon aria-hidden="true" />项目原理图</span><strong>查看完整的 focus-hint 对比</strong><ArrowRight aria-hidden="true" /></div></a>
          </div>
        </section>

        <section className="section scenarios-section" id="scenarios">
          <div className="page-width">
            <SectionHeading eyebrow="USE CASES" title="同一套 Vision，进入不同的真实工作流。" description="从一次图片提问，到长截图处理、前端重建和 GUI 操作；Agent 根据问题选择工具，而不是把所有视觉任务塞进一个黑盒。" />
            <div className="scenario-workbench reveal">
              <div className="scenario-tabs" role="tablist" aria-label="视觉应用场景">
                {scenarios.map((scenario, index) => {
                  const Icon = scenario.icon
                  const selected = index === activeScenario
                  return <button type="button" role="tab" aria-selected={selected} className={`scenario-tab ${selected ? 'scenario-tab--active' : ''}`} key={scenario.id} onClick={() => setActiveScenario(index)}><span className="scenario-tab__icon"><Icon aria-hidden="true" /></span><span className="scenario-tab__copy"><strong>{scenario.label}</strong><small>{scenario.description}</small></span><ArrowRight className="scenario-tab__arrow" aria-hidden="true" /></button>
                })}
              </div>
              <article className="scenario-preview" ref={scenarioPreviewRef}>
                <div className="scenario-preview__topbar"><span className="scenario-preview__eyebrow">{active.eyebrow}</span><span className="scenario-preview__index">0{activeScenario + 1} / 0{scenarios.length}</span></div>
                <div className="scenario-preview__media"><ScenarioPreview scenario={active} /><div className="scenario-preview__scanline" aria-hidden="true" /><span className="scenario-preview__status"><span /> visual context ready</span></div>
                <div className="scenario-preview__body"><h3>{active.title}</h3><p>{active.description}</p><div className="scenario-preview__tags">{active.tags.map((tag) => <span key={tag}>{tag}</span>)}</div></div>
              </article>
            </div>
            <div className="capability-panel reveal">
              <div className="capability-panel__copy"><span className="capability-panel__icon"><Network aria-hidden="true" /></span><p className="eyebrow"><span />TOOL ROUTING MAP</p><h3>每种场景，调用恰好需要的工具。</h3><p>图中的色块表示推荐工作流中会进入的工具，不是性能评分。点击任意一行，可以切换上方场景。</p></div>
              <CapabilityChart scenarios={scenarios} activeIndex={activeScenario} onSelect={setActiveScenario} />
            </div>
          </div>
        </section>

        <section className="section tools-section" id="tools">
          <div className="page-width">
            <div className="tools-heading-row"><SectionHeading eyebrow="THE TOOLKIT" title="一个工具，回答一类清晰的问题。" description="按 Agent 的问题拆分视觉接口：理解、定位、清点、追踪、裁切。每个命令都能独立使用，也能在同一工作流里前后衔接。" /><div className="tools-heading-row__badge reveal"><Terminal aria-hidden="true" />Shell-native · Agent-friendly</div></div>
            <div className="tools-grid">
              {tools.map(({ id, icon: Icon, question, description, command }, index) => <article className="tool-card reveal" key={id}><div className="tool-card__header"><span className="tool-card__icon"><Icon aria-hidden="true" /></span><span className="tool-card__index">0{index + 1}</span></div><p className="tool-card__name">{id}</p><h3>{question}</h3><p>{description}</p><code>{command}</code></article>)}
            </div>
            <div className="tool-chain reveal" aria-label="视觉工具从理解到验证的组合链路"><span className="tool-chain__label">Coarse</span>{tools.map(({ id, icon: Icon }, index) => <div className="tool-chain__step" key={id}><span><Icon aria-hidden="true" />{id}</span>{index < tools.length - 1 ? <ArrowRight aria-hidden="true" /> : null}</div>)}<span className="tool-chain__label">Exact</span></div>
          </div>
        </section>

        <section className="section integration-section">
          <div className="integration-card page-width reveal">
            <div className="integration-card__glow" />
            <div className="integration-card__content"><span className="integration-icon"><PlugZap aria-hidden="true" /></span><p className="eyebrow eyebrow--light"><span />START WITH THE TOOLKIT</p><h2>给你正在使用的 coding agent 装上眼睛。</h2><p>安装 CLI 与 vision-tools skill；需要无缝粘贴图片时，再启用 Codex / Claude Code 代理或 Pi / OpenCode 原生扩展。</p><div className="integration-actions"><a className="button button--light" href={repoUrl} target="_blank" rel="noreferrer">阅读 Quick Start<ArrowRight aria-hidden="true" /></a><a className="button button--ghost-light" href={`${repoUrl}/blob/main/AGENT_INSTALL.md`} target="_blank" rel="noreferrer"><Code2 aria-hidden="true" />无缝接入指南</a></div></div>
            <div className="install-terminal"><div className="install-terminal__bar"><div><span /><span /><span /></div><span>terminal</span></div><div className="install-terminal__body"><p><span>$</span> install the vision skill</p><code>{installCommand}</code><button type="button" onClick={copyInstallCommand}>{copied ? <CheckCircle2 aria-hidden="true" /> : <Copy aria-hidden="true" />}{copied ? '已复制' : '复制命令'}</button></div><div className="install-terminal__status"><span><Zap aria-hidden="true" /> ready for visual tasks</span><span>MIT License</span></div></div>
          </div>
        </section>
      </main>

      <footer className="site-footer"><div className="page-width site-footer__inner"><div className="site-footer__brand"><BrandMark compact /><div><strong>agent-vision-toolkit</strong><span>Give text-only LLM agents eyes.</span></div></div><div className="site-footer__links"><a href={`${repoUrl}/blob/main/README.md`} target="_blank" rel="noreferrer">README</a><a href={`${repoUrl}/issues`} target="_blank" rel="noreferrer">Issues</a><a href={`${repoUrl}/blob/main/LICENSE`} target="_blank" rel="noreferrer">License</a><a href={repoUrl} target="_blank" rel="noreferrer" aria-label="GitHub repository"><GitFork aria-hidden="true" /></a></div></div></footer>
    </div>
  )
}

export default App
