import {
  ApiOutlined,
  ApartmentOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  DashboardOutlined,
  FolderOutlined,
  MenuOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { Button, Drawer, Input, Layout, Menu, type MenuProps } from 'antd'
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import type { ProjectSection } from '../projects/project-routing'
import {
  navigationPath,
  sectionLabels,
  shellNavigationItems,
  visibleSections,
} from './navigation-config'
import { useNavigationState } from './use-navigation-state'

interface ShellSidebarProps {
  userId: string
  isSystemAdmin: boolean
  section: ProjectSection
  pathFor: (section: ProjectSection) => string
}

const shortcuts = [
  { section: 'dashboard', label: '总览', icon: <DashboardOutlined /> },
  { section: 'apis', label: '接口', icon: <ApiOutlined /> },
  { section: 'workflows', label: '编排', icon: <ApartmentOutlined /> },
  { section: 'assets', label: '用例', icon: <FolderOutlined /> },
  { section: 'reports', label: '报告', icon: <BarChartOutlined /> },
  { section: 'release', label: '门禁', icon: <SafetyCertificateOutlined /> },
] as const

export default function ShellSidebar({
  userId,
  isSystemAdmin,
  section,
  pathFor,
}: ShellSidebarProps) {
  const state = useNavigationState(userId, section, isSystemAdmin, 'directory')
  const navigate = useNavigate()
  const trigger = useRef<HTMLButtonElement>(null)
  const [query, setQuery] = useState('')
  const handleLeafClick: NonNullable<MenuProps['onClick']> = ({ key, domEvent }) => {
    const target = visibleSections(isSystemAdmin).find((item) => item === key)
    if (!target) return
    state.setDrawerOpen(false)
    const clickedLink = domEvent.target instanceof Element && domEvent.target.closest('a')
    if (!clickedLink) navigate(navigationPath(target, pathFor))
  }
  const normalized = query.trim().toLowerCase()
  const items = normalized
    ? visibleSections(isSystemAdmin)
        .filter((item) => sectionLabels[item].toLowerCase().includes(normalized))
        .map((item) => ({
          key: item,
          label: <Link to={navigationPath(item, pathFor)}>{sectionLabels[item]}</Link>,
        }))
    : shellNavigationItems(isSystemAdmin, section, pathFor)
  const openDirectory = (
    <Button
      ref={trigger}
      className={state.mobile ? 'shell-navigation-trigger' : 'shell-rail-directory'}
      type={state.mobile ? 'default' : 'text'}
      aria-label={state.mobile ? '打开导航' : '全部模块'}
      aria-expanded={state.drawerOpen}
      icon={state.mobile ? <MenuOutlined /> : <AppstoreOutlined />}
      onClick={() => state.setDrawerOpen(true)}
    >
      {!state.mobile && <span>全部</span>}
    </Button>
  )
  return (
    <>
      {state.mobile ? (
        openDirectory
      ) : (
        <Layout.Sider width={68} theme="light" className="sidebar">
          <nav className="shell-task-rail" aria-label="常用任务">
            {shortcuts.map((item) => (
              <Link
                key={item.section}
                to={navigationPath(item.section, pathFor)}
                aria-label={sectionLabels[item.section]}
                aria-current={section === item.section ? 'page' : undefined}
                className={section === item.section ? 'is-active' : undefined}
              >
                {item.icon}
                <span>{item.label}</span>
              </Link>
            ))}
            <div className="shell-rail-footer">{openDirectory}</div>
          </nav>
        </Layout.Sider>
      )}
      <Drawer
        title="全部模块"
        placement="left"
        size={320}
        open={state.drawerOpen}
        onClose={() => state.setDrawerOpen(false)}
        className="shell-navigation-drawer"
        afterOpenChange={(open) => !open && trigger.current?.focus()}
      >
        <Input.Search
          aria-label="搜索模块"
          placeholder="搜索模块名称"
          value={query}
          allowClear
          onChange={(event) => setQuery(event.target.value)}
        />
        <nav className="shell-navigation-scroll" aria-label="功能导航">
          <Menu
            aria-label="功能菜单"
            theme="light"
            mode="inline"
            selectedKeys={[section]}
            openKeys={normalized ? undefined : state.openKeys}
            onOpenChange={state.changeOpenKeys}
            items={items}
            onClick={handleLeafClick}
          />
        </nav>
      </Drawer>
    </>
  )
}
