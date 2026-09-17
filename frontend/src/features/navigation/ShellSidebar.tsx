import { ApiOutlined, MenuFoldOutlined, MenuOutlined, MenuUnfoldOutlined } from '@ant-design/icons'
import { Button, ConfigProvider, Drawer, Layout, Menu, type MenuProps } from 'antd'
import { useRef } from 'react'
import { useNavigate } from 'react-router-dom'

import type { ProjectSection } from '../projects/project-routing'
import { navigationPath, shellNavigationItems, visibleSections } from './navigation-config'
import { useNavigationState } from './use-navigation-state'

interface ShellSidebarProps {
  userId: string
  isSystemAdmin: boolean
  section: ProjectSection
  pathFor: (section: ProjectSection) => string
}

export default function ShellSidebar({
  userId,
  isSystemAdmin,
  section,
  pathFor,
}: ShellSidebarProps) {
  const state = useNavigationState(userId, section, isSystemAdmin)
  const navigate = useNavigate()
  const handleLeafClick: NonNullable<MenuProps['onClick']> = ({ key, domEvent }) => {
    if (state.mobile) state.setDrawerOpen(false)
    const target = visibleSections(isSystemAdmin).find((item) => item === key)
    const clickedLink = domEvent.target instanceof Element && domEvent.target.closest('a')
    // Links keep native browser behavior; row/icon/keyboard activation uses the same router guard.
    if (target && !clickedLink) navigate(navigationPath(target, pathFor))
  }
  const drawerTrigger = useRef<HTMLButtonElement>(null)
  // Each Menu mode owns its popup lifecycle; the workspace keeps the same instance.
  const navigation = (
    <div className={`shell-sidebar-body${state.collapsed ? ' shell-sidebar-collapsed' : ''}`}>
      <div className="brand">
        <ApiOutlined />
        {!state.collapsed && <span>FlowTest</span>}
      </div>
      <nav className="shell-navigation-scroll" aria-label="功能导航">
        <ConfigProvider theme={{ components: { Menu: { darkItemSelectedBg: '#1677ff' } } }}>
          <Menu
            key={`menu:${state.collapsed}`}
            aria-label="功能菜单"
            theme="dark"
            mode="inline"
            inlineCollapsed={state.collapsed}
            selectedKeys={[section]}
            openKeys={state.openKeys}
            onOpenChange={state.changeOpenKeys}
            triggerSubMenuAction="click"
            items={shellNavigationItems(isSystemAdmin, section, pathFor)}
            onClick={handleLeafClick}
          />
        </ConfigProvider>
      </nav>
      <div className="shell-sidebar-footer">
        <Button
          type="text"
          block
          aria-label={state.mobile ? '关闭导航' : state.collapsed ? '展开侧栏' : '收起侧栏'}
          icon={state.collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          onClick={state.mobile ? () => state.setDrawerOpen(false) : state.toggleCollapsed}
        >
          {!state.collapsed && (state.mobile ? '关闭导航' : '收起侧栏')}
        </Button>
      </div>
    </div>
  )
  if (state.mobile) {
    return (
      <>
        <Button
          ref={drawerTrigger}
          className="shell-navigation-trigger"
          aria-label="打开导航"
          aria-expanded={state.drawerOpen}
          icon={<MenuOutlined />}
          onClick={() => state.setDrawerOpen(true)}
        />
        <Drawer
          title="FlowTest 导航"
          placement="left"
          size={224}
          open={state.drawerOpen}
          onClose={() => state.setDrawerOpen(false)}
          className="shell-navigation-drawer"
          styles={{ body: { padding: 0 } }}
          afterOpenChange={(open) => !open && drawerTrigger.current?.focus()}
        >
          {navigation}
        </Drawer>
      </>
    )
  }
  return (
    <Layout.Sider
      width={224}
      collapsedWidth={72}
      collapsed={state.collapsed}
      trigger={null}
      theme="dark"
      className="sidebar"
    >
      {navigation}
    </Layout.Sider>
  )
}
