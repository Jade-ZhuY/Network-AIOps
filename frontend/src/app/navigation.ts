import {
  BookOpen,
  ChartNoAxesCombined,
  ClipboardCheck,
  LayoutDashboard,
  MessagesSquare,
  ScanLine,
  ClipboardList,
  type LucideIcon,
} from "lucide-react";

export interface NavigationModule {
  path: string;
  title: string;
  subtitle: string;
  group: string;
  icon: LucideIcon;
  adminOnly?: boolean;
  javaOnly?: boolean;
}
// New business modules register navigation here and a page in App.tsx.
export const modules: NavigationModule[] = [
  {
    path: "/",
    title: "工作台总览",
    subtitle: "Workspace overview",
    group: "主导航",
    icon: LayoutDashboard,
  },
  {
    path: "/tickets",
    title: "咨询单管理",
    subtitle: "Consultation tickets",
    group: "业务管理",
    icon: ClipboardList,
    javaOnly: true,
  },
  {
    path: "/investigation",
    title: "智能调查",
    subtitle: "Agent workspace",
    group: "智能工作空间",
    icon: MessagesSquare,
  },
  {
    path: "/knowledge",
    title: "知识资料",
    subtitle: "Knowledge library",
    group: "智能工作空间",
    icon: BookOpen,
  },
  {
    path: "/metrics",
    title: "正式指标",
    subtitle: "Reviewed metrics",
    group: "治理与管理",
    icon: ChartNoAxesCombined,
  },
  {
    path: "/governance",
    title: "治理反馈",
    subtitle: "Governance feedback",
    group: "治理与管理",
    icon: ClipboardCheck,
  },
  {
    path: "/audit",
    title: "执行审计",
    subtitle: "Execution audit",
    group: "治理与管理",
    icon: ScanLine,
    adminOnly: true,
  },
];
export const suggestions = [
  {
    tag: "综合诊断",
    title: "BGP 邻居为何频繁断连？",
    description: "关联告警、接口指标与协议知识",
    question:
      "R2 昨天下午 BGP 邻居频繁断连，结合接口丢包率和告警分析可能原因。",
  },
  {
    tag: "指标查询",
    title: "查询告警与丢包率",
    description: "按设备和时间范围查询业务数据",
    question: "查询 R2 昨天有多少严重告警，eth1 的平均丢包率是多少？",
  },
  {
    tag: "知识问答",
    title: "理解 OSPF 与 RIP 的区别",
    description: "检索协议资料，追溯原文出处",
    question: "OSPF 为什么使用链路状态数据库？与 RIP 的收敛机制有什么区别？",
  },
];
