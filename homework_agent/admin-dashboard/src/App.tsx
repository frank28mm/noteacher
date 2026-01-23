import React, { useState, useEffect, useCallback } from 'react';
import { apiClient } from '@/services/api';
import { Header } from '@/components/ui/Header';
import { useToast } from '@/components/ui/Toast';
import {
  useDashboard,
  useUsers,
  useFeedbackUsers,
  useFeedbackMessages,
  useRedemptions,
  useBatches,
  useAuditLogs,
  useUserSubmissions,
  useUserReports,
  useUsageLedger,
  type DashboardStats,
  type FeedbackUser,
  type FeedbackMessage,
  type RedemptionItem,
  type BatchItem,
} from '@/hooks/useAdminSWR';
import type {
  AdminUserDetail,
  AuditLogItem,
  AdminSubmissionItem,
  AdminReportItem,
  UsageLedgerItem
} from '@/services/types';

type TabKey = 'dashboard' | 'users' | 'submissions' | 'redemptions' | 'feedback' | 'audit';

interface TabConfig {
  key: TabKey;
  icon: string;
  label: string;
  description: string;
}

const TAB_CONFIG: TabConfig[] = [
  { 
    key: 'dashboard', 
    icon: '📊', 
    label: '数据看板 / DASHBOARD',
    description: '> 业务核心指标概览 / Business Overview'
  },
  { 
    key: 'users', 
    icon: '#', 
    label: '用户管理 / USERS',
    description: '> 管理用户、积分与钱包 / Manage users & credits'
  },
  { 
    key: 'submissions', 
    icon: '#', 
    label: '作业记录 / SUBMISSIONS',
    description: '> 查看作业、报告与用量 / View homeworks & reports'
  },
  { 
    key: 'redemptions', 
    icon: '#', 
    label: '兑换码 / REDEMPTIONS',
    description: '> 追踪兑换码状态 / Track codes & coupons'
  },
  { 
    key: 'feedback', 
    icon: '#', 
    label: '用户反馈 / FEEDBACK',
    description: '> 用户消息与支持 / User messages'
  },
  { 
    key: 'audit', 
    icon: '#', 
    label: '操作日志 / AUDIT_LOGS',
    description: '> 系统操作审计 / System logs'
  },
];



const Admin: React.FC = () => {
  const { showToast } = useToast();
  const [token, setToken] = useState(localStorage.getItem('admin_token') || '');
  const [isAuthenticated, setIsAuthenticated] = useState(!!localStorage.getItem('admin_token'));
  const [activeTab, setActiveTab] = useState<TabKey>('dashboard');
  
  const [searchPhone, setSearchPhone] = useState('');
  const [searchTrigger, setSearchTrigger] = useState('');
  
  // Redemptions State
  const [redemptionView, setRedemptionView] = useState<'list' | 'batch'>('list');
  const [selectedCodes, setSelectedCodes] = useState<Set<string>>(new Set());
  
  const [selectedFeedbackUser, setSelectedFeedbackUser] = useState<string | null>(null);
  const [replyInput, setReplyInput] = useState('');

  const [selectedUser, setSelectedUser] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'list' | 'detail'>('list');
  const [subTab, setSubTab] = useState<'submissions' | 'reports' | 'ledger'>('submissions');
  
  // Generation State
  const [showGenForm, setShowGenForm] = useState(false);
  const [genConfig, setGenConfig] = useState({
    batch_id: `BATCH_${new Date().toISOString().slice(0,10).replace(/-/g,'')}`,
    card_type: 'trial_pack',
    bt_amount: 5000,
    coupon_amount: 0,
    premium_days: 0,
    target_tier: 'S1',
    count: 1,
    cp_multiplier: 1,
    expires_days: 30
  });
  const [generatedCodes, setGeneratedCodes] = useState<string[]>([]);
  const [generating, setGenerating] = useState(false);

  const feedbackScrollRef = React.useRef<HTMLDivElement>(null);

  const authToken = isAuthenticated ? token : null;
  
  const { data: dashboardData, error: dashboardError } = useDashboard(authToken);
  const { data: usersData, isLoading: usersLoading, mutate: mutateUsers } = useUsers(authToken, searchTrigger);
  const { data: feedbackUsersData } = useFeedbackUsers(authToken);
  const { data: feedbackMessagesData, mutate: mutateFeedbackMessages } = useFeedbackMessages(authToken, selectedFeedbackUser);
  const { data: redemptionsData, isLoading: redemptionsLoading, mutate: mutateRedemptions } = useRedemptions(authToken);
  const { data: batchesData, mutate: mutateBatches } = useBatches(authToken);
  const { data: auditData, isLoading: auditLoading } = useAuditLogs(authToken);
  const { data: userSubmissionsData } = useUserSubmissions(authToken, selectedUser);
  const { data: userReportsData } = useUserReports(authToken, selectedUser);
  const { data: usageLedgerData } = useUsageLedger(authToken, selectedUser);

  const dashboardStats: DashboardStats | null = dashboardData ?? null;
  const users: AdminUserDetail[] = usersData?.users ?? [];
  
  console.log('Users Data:', usersData);
  console.log('Users List:', users);

  const feedbackUsers: FeedbackUser[] = feedbackUsersData?.items ?? [];
  const feedbackMessages: FeedbackMessage[] = feedbackMessagesData?.messages ?? [];
  const redemptions: RedemptionItem[] = redemptionsData?.items ?? [];
  const batches: BatchItem[] = batchesData?.items ?? [];
  const auditLogs: AuditLogItem[] = auditData?.items ?? [];
  const userSubmissions: AdminSubmissionItem[] = userSubmissionsData?.items ?? [];
  const userReports: AdminReportItem[] = userReportsData?.items ?? [];
  const usageLedger: UsageLedgerItem[] = usageLedgerData?.items ?? [];

  useEffect(() => {
    if (dashboardError?.response?.status === 403) {
      showToast('Invalid Token', 'error');
      setIsAuthenticated(false);
    }
  }, [dashboardError, showToast]);

  const saveToken = () => {
    if (!token.trim()) return;
    localStorage.setItem('admin_token', token.trim());
    setIsAuthenticated(true);
    showToast('Login successful', 'success');
  };

  const clearToken = () => {
    localStorage.removeItem('admin_token');
    setToken('');
    setIsAuthenticated(false);
  };

  const handleSearchUsers = useCallback(() => {
    setSearchTrigger(searchPhone);
  }, [searchPhone]);

  const handleAdjustWallet = async (userId: string, field: 'bt_subscription_delta' | 'report_coupons_delta', defaultVal: string) => {
    const delta = prompt('DELTA_AMOUNT (+/-):', defaultVal);
    if (!delta || isNaN(Number(delta))) return;
    try {
      await apiClient.post(
        `/admin/users/${userId}/wallet_adjust`,
        { [field]: Number(delta), reason: 'admin_manual' },
        { headers: { 'X-Admin-Token': token } }
      );
      showToast('ADJUST_OK', 'success');
      mutateUsers();
    } catch {
      showToast('ADJUST_FAIL', 'error');
    }
  };

  const handleGenerateCards = async () => {
    if (!genConfig.batch_id) {
      showToast('Batch ID is required', 'error');
      return;
    }
    setGenerating(true);
    try {
      const calculatedBT = (genConfig.cp_multiplier || 0) * 12400;
      
      const payload = {
        card_type: genConfig.card_type,
        bt_amount: calculatedBT,
        coupon_amount: genConfig.coupon_amount,
        premium_days: genConfig.premium_days,
        count: genConfig.count,
        batch_id: genConfig.batch_id,
        expires_days: genConfig.expires_days,
        meta: {
          target_tier: genConfig.target_tier
        }
      };

      const res = await apiClient.post('/admin/redeem_cards/generate', payload, {
        headers: { 'X-Admin-Token': token }
      });
      setGeneratedCodes(res.data?.codes || []);
      showToast(`生成成功 / SUCCESS: ${res.data?.count}`, 'success');
      mutateRedemptions();
      mutateBatches();
    } catch (err) {
      console.error(err);
      showToast('Generate failed', 'error');
    } finally {
      setGenerating(false);
    }
  };

  const handleDisableBatch = async (batchId: string) => {
    if (!confirm(`确定要作废批次 ${batchId} 中的所有未兑换卡密吗？`)) return;
    try {
      await apiClient.post(`/admin/redeem_cards/batches/${batchId}/disable`, {}, {
        headers: { 'X-Admin-Token': token }
      });
      showToast('Batch disabled', 'success');
      mutateBatches();
    } catch {
      showToast('Action failed', 'error');
    }
  };

  const handleBulkUpdate = async (status: 'disabled' | 'active') => {
    if (selectedCodes.size === 0) return;
    if (!confirm(`确定要将 ${selectedCodes.size} 张卡密设为 ${status} 吗？`)) return;
    try {
      await apiClient.post('/admin/redeem_cards/bulk_update', {
        codes: Array.from(selectedCodes),
        status
      }, {
        headers: { 'X-Admin-Token': token }
      });
      showToast('Bulk update success', 'success');
      setSelectedCodes(new Set());
      mutateRedemptions();
    } catch {
      showToast('Bulk update failed', 'error');
    }
  };

  const downloadCSV = () => {
    const header = "Code,BatchID,Type,BT,Coupon,PremiumDays,TargetTier\n";
    const rows = generatedCodes.map(code => 
      `${code},${genConfig.batch_id},${genConfig.card_type},${genConfig.bt_amount},${genConfig.coupon_amount},${genConfig.premium_days},${genConfig.target_tier}`
    ).join("\n");
    const blob = new Blob([header + rows], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `redeem_cards_${genConfig.batch_id}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  useEffect(() => {
    if (selectedFeedbackUser && feedbackMessagesData) {
      setTimeout(() => feedbackScrollRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
    }
  }, [feedbackMessagesData, selectedFeedbackUser]);

  const sendReply = async () => {
    if (!selectedFeedbackUser || !replyInput.trim()) return;
    try {
      await apiClient.post(
        `/admin/feedback/${selectedFeedbackUser}`,
        { content: replyInput },
        { headers: { 'X-Admin-Token': token } }
      );
      setReplyInput('');
      mutateFeedbackMessages();
    } catch {
      showToast('Send failed', 'error');
    }
  };

  const handleSelectUser = (userId: string) => {
    setSelectedUser(userId);
    setViewMode('detail');
  };

  const handleBackToList = () => {
    setSelectedUser(null);
    setViewMode('list');
  };

  const currentTabConfig = TAB_CONFIG.find(t => t.key === activeTab);

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-white font-mono flex flex-col items-center justify-center p-6 text-sm">
        <div className="w-full max-w-sm border border-gray-900 p-8 space-y-6">
          <div className="text-center">
            <h1 className="text-lg font-bold text-gray-900 border-b-2 border-gray-900 inline-block pb-1">ADMIN_CONSOLE</h1>
            <p className="text-gray-500 mt-2 text-xs">./authenticate --token</p>
          </div>
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && saveToken()}
            placeholder="ENTER_TOKEN..."
            className="w-full px-3 py-2 bg-white border border-gray-300 focus:border-gray-900 focus:outline-none transition-colors rounded-none placeholder-gray-400"
          />
          <button
            onClick={saveToken}
            className="w-full py-2 bg-white border border-gray-900 text-gray-900 font-bold hover:bg-gray-100 active:bg-gray-200 transition-all rounded-none"
          >
            [ ENTER_SYSTEM ]
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white font-mono text-sm text-gray-800">
      <Header title="TINT管理后台 / TINT ADMIN" showBack={false} className="bg-white sticky top-0 z-10 border-b-2 border-gray-900" />
      
      <div className="p-4 md:p-8 max-w-5xl mx-auto">
        {/* Tab Navigation */}
        <div className="mb-8">
          <div className="flex justify-between items-end mb-4 border-b border-gray-200 pb-2">
            <span className="text-xs font-bold text-gray-400">功能模块 / MODULES</span>
            <button onClick={clearToken} className="text-xs text-red-600 hover:underline">
              [ 退出 / LOGOUT ]
            </button>
          </div>
          <div className="flex flex-wrap gap-2 md:gap-4">
            {TAB_CONFIG.map((tab) => (
              <button
                key={tab.key}
                onClick={() => {
                  setActiveTab(tab.key);
                  setSelectedFeedbackUser(null);
                  if (tab.key !== 'submissions') {
                    setViewMode('list');
                    setSelectedUser(null);
                  }
                }}
                className={`px-3 py-1.5 text-xs font-bold transition-all border ${
                  activeTab === tab.key
                    ? 'border-gray-900 bg-gray-900 text-white'
                    : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-900'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Current Tab Description */}
        {currentTabConfig && (
          <div className="mb-6 border-l-2 border-gray-900 pl-4 py-1">
            <div className="font-bold text-gray-900 text-lg">{currentTabConfig.label}</div>
            <div className="text-xs text-gray-500 font-mono mt-1">{currentTabConfig.description}</div>
          </div>
        )}

        {/* Dashboard Tab */}
        {activeTab === 'dashboard' && (
          <div className="space-y-8">
            {!dashboardStats ? (
              <div className="py-12 text-gray-400 font-mono text-xs">{'>'} fetching_stats...</div>
            ) : (
              <>
                {/* Section 1: KPI */}
                <div>
                  <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4 border-b border-gray-200 pb-2">1. 核心北极星指标 / KPI</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div className="border border-gray-200 p-5 hover:border-gray-900 transition-colors bg-white group">
                      <div className="text-[10px] text-gray-400 uppercase mb-1 group-hover:text-gray-900">Total Users</div>
                      <div className="text-3xl font-bold text-gray-900">{dashboardStats.kpi.total_users}</div>
                      <div className="mt-2 text-xs text-gray-500">总用户数</div>
                    </div>
                    <div className="border border-gray-200 p-5 hover:border-gray-900 transition-colors bg-white group">
                      <div className="text-[10px] text-gray-400 uppercase mb-1 group-hover:text-gray-900">Paid Ratio</div>
                      <div className="text-3xl font-bold text-gray-900">{dashboardStats.kpi.paid_ratio}</div>
                      <div className="mt-2 text-xs text-gray-500">付费渗透率</div>
                    </div>
                    <div className="border border-gray-200 p-5 hover:border-gray-900 transition-colors bg-white group">
                      <div className="text-[10px] text-gray-400 uppercase mb-1 group-hover:text-gray-900">DAU (Today)</div>
                      <div className="text-3xl font-bold text-gray-900">{dashboardStats.kpi.dau}</div>
                      <div className="mt-2 text-xs text-gray-500">今日活跃用户</div>
                    </div>
                    <div className="border border-gray-200 p-5 hover:border-gray-900 transition-colors bg-white group">
                      <div className="text-[10px] text-gray-400 uppercase mb-1 group-hover:text-gray-900">Revenue (Month)</div>
                      <div className="text-3xl font-bold text-gray-900">{dashboardStats.kpi.mrr}</div>
                      <div className="mt-2 text-xs text-gray-500">本月收入 (MRR)</div>
                    </div>
                  </div>
                </div>

                {/* Section 2: Cost & Usage */}
                <div>
                  <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4 border-b border-gray-200 pb-2">2. 消耗与成本 / COST & USAGE</h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="border border-gray-200 p-5 hover:border-gray-900 transition-colors bg-white">
                      <div className="text-[10px] text-gray-400 uppercase mb-1">Tokens Used (Today)</div>
                      <div className="text-2xl font-bold text-gray-900 font-mono">{dashboardStats.cost.tokens_today}</div>
                      <div className="mt-1 text-xs text-gray-500">今日 Token 消耗</div>
                    </div>
                    <div className="border border-gray-200 p-5 hover:border-gray-900 transition-colors bg-white">
                      <div className="text-[10px] text-gray-400 uppercase mb-1">Submissions (Today)</div>
                      <div className="text-2xl font-bold text-gray-900 font-mono">{dashboardStats.cost.subs_today}</div>
                      <div className="mt-1 text-xs text-gray-500">今日作业量</div>
                    </div>
                    <div className="border border-gray-200 p-5 hover:border-gray-900 transition-colors bg-white">
                      <div className="text-[10px] text-gray-400 uppercase mb-1">Avg Cost / Sub</div>
                      <div className="text-2xl font-bold text-gray-900 font-mono">{dashboardStats.cost.avg_cost}</div>
                      <div className="mt-1 text-xs text-gray-500">单次作业平均成本</div>
                    </div>
                  </div>
                </div>

                {/* Section 3: Conversion & Health */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                  <div>
                    <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4 border-b border-gray-200 pb-2">3. 转化漏斗 / CONVERSION</h3>
                    <div className="grid grid-cols-1 gap-4">
                      <div className="border border-gray-200 p-4 flex justify-between items-center bg-gray-50">
                        <div>
                          <div className="text-sm font-bold text-gray-900">试用 &rarr; 付费转化</div>
                          <div className="text-[10px] text-gray-500">Trial to Paid Conversion</div>
                        </div>
                        <div className="text-xl font-bold text-gray-900">{dashboardStats.conversion.trial_conversion}</div>
                      </div>
                      <div className="border border-gray-200 p-4 flex justify-between items-center bg-gray-50">
                        <div>
                          <div className="text-sm font-bold text-gray-900">卡密兑换率</div>
                          <div className="text-[10px] text-gray-500">Redemption Rate</div>
                        </div>
                        <div className="text-xl font-bold text-gray-900">{dashboardStats.conversion.card_redemption_rate}</div>
                      </div>
                    </div>
                  </div>

                  <div>
                    <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-4 border-b border-gray-200 pb-2">4. 系统健康度 / HEALTH</h3>
                    <div className="grid grid-cols-1 gap-4">
                      <div className="border border-gray-200 p-4 flex justify-between items-center bg-white border-l-4 border-l-green-500">
                        <div>
                          <div className="text-sm font-bold text-gray-900">失败率 (Error Rate)</div>
                          <div className="text-[10px] text-gray-500">Submissions with warnings</div>
                        </div>
                        <div className="text-xl font-bold text-gray-900">{dashboardStats.health.error_rate}</div>
                      </div>
                      <div className="border border-gray-200 p-4 flex justify-between items-center bg-white border-l-4 border-l-blue-500">
                        <div>
                          <div className="text-sm font-bold text-gray-900">平均耗时 (Latency P50)</div>
                          <div className="text-[10px] text-gray-500">End-to-end processing</div>
                        </div>
                        <div className="text-xl font-bold text-gray-900">{dashboardStats.health.latency_p50}</div>
                      </div>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* Users Tab */}
        {activeTab === 'users' && (
          <div className="space-y-6">
            <div className="flex gap-0 border border-gray-300 w-full md:w-1/2">
              <input
                value={searchPhone}
                onChange={(e) => setSearchPhone(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearchUsers()}
                placeholder="search_query: phone / user_id..."
                className="flex-1 px-3 py-2 bg-transparent border-none focus:outline-none text-gray-900 placeholder-gray-400"
              />
              <button 
                onClick={handleSearchUsers} 
                className="px-4 py-2 bg-gray-100 border-l border-gray-300 text-gray-700 font-bold hover:bg-gray-200"
              >
                EXEC
              </button>
            </div>

            {usersLoading ? (
              <div className="py-12 text-gray-400 font-mono text-xs">
                {'>'} fetching_data...
              </div>
            ) : users.length === 0 ? (
              <div className="py-12 text-gray-400 font-mono text-xs">
                {'>'} no_records_found (Debug: Data={JSON.stringify(usersData)})
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4">
                {users.map((item: AdminUserDetail) => {
                  const u = item.user;
                  const w = item.wallet;
                  return (
                    <div key={u.user_id} className="border border-gray-200 p-4 hover:border-gray-900 transition-colors bg-white">
                      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-4 gap-2">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-gray-900 text-base">{u.phone}</span>
                            <span className="text-xs text-gray-400 bg-gray-50 px-1 border border-gray-100">
                              ID:{u.user_id.slice(0, 8)}
                            </span>
                          </div>
                          <div className="text-[10px] text-gray-500 mt-1 font-mono">
                            created: {u.created_at ? new Date(u.created_at).toLocaleDateString('zh-CN') : 'N/A'} 
                            {' | '}
                            last_login: {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString('zh-CN') : 'N/A'}
                          </div>
                        </div>
                        <div className="text-right">
                          <span className="text-xs font-bold border border-gray-900 px-2 py-0.5 inline-block">
                            {w?.plan_tier || 'FREE'}
                          </span>
                        </div>
                      </div>
                      
                      <div className="border-t border-b border-gray-100 py-3 grid grid-cols-2 md:grid-cols-4 gap-4 text-xs mb-4 bg-gray-50/30">
                        <div>
                          <span className="text-gray-400 block mb-1">TOKENS / BT</span>
                          <span className="font-bold">{((w?.bt_trial || 0) + (w?.bt_subscription || 0)).toLocaleString()}</span>
                        </div>
                        <div>
                          <span className="text-gray-400 block mb-1">报告券 / COUPONS</span>
                          <span className="font-bold">{w?.report_coupons || 0}</span>
                        </div>
                        <div>
                          <span className="text-gray-400 block mb-1">冻结 / FROZEN BT</span>
                          <span className="text-gray-600">{(w?.bt_report_reserve || 0).toLocaleString()}</span>
                        </div>
                        <div>
                          <span className="text-gray-400 block mb-1">订阅状态 / SUB</span>
                          <span className="text-gray-600">{w?.plan_tier === 'premium' ? '高级版' : '免费版'}</span>
                        </div>
                      </div>

                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={() => handleAdjustWallet(u.user_id, 'bt_subscription_delta', '0')}
                          className="px-3 py-1 text-[10px] border border-gray-300 text-gray-600 hover:border-gray-900 hover:text-gray-900 transition-all uppercase"
                        >
                          [ ADJ_TOKENS ]
                        </button>
                        <button
                          onClick={() => handleAdjustWallet(u.user_id, 'report_coupons_delta', '1')}
                          className="px-3 py-1 text-[10px] border border-gray-900 text-gray-900 font-bold hover:bg-gray-900 hover:text-white transition-all uppercase"
                        >
                          [ 调整券 / ADJ_COUPON ]
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Feedback Tab */}
        {activeTab === 'feedback' && (
          <div className="flex h-[calc(100vh-280px)] border border-gray-200">
            <div className={`w-full md:w-72 border-r border-gray-200 flex flex-col ${selectedFeedbackUser ? 'hidden md:flex' : 'flex'}`}>
              <div className="p-3 border-b border-gray-200 bg-gray-50 text-xs font-bold text-gray-500 uppercase tracking-wider">
                inbox
              </div>
              <div className="flex-1 overflow-y-auto">
                {feedbackUsers.length === 0 ? (
                  <div className="p-4 text-xs text-gray-400">{'>'} empty</div>
                ) : feedbackUsers.map(u => (
                  <button
                    key={u.user_id}
                    onClick={() => setSelectedFeedbackUser(u.user_id)}
                    className={`w-full text-left p-3 border-b border-gray-100 hover:bg-gray-50 transition-colors group ${selectedFeedbackUser === u.user_id ? 'bg-gray-100' : ''}`}
                  >
                    <div className="flex justify-between items-center mb-1">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-xs text-gray-900 group-hover:underline">{u.user_id.slice(0, 8)}</span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setSearchPhone(u.user_id);
                            setActiveTab('users');
                          }}
                          className="text-[9px] border border-gray-200 px-1 hover:bg-gray-200 text-gray-500 rounded"
                          title="跳转至用户管理"
                        >
                          🔍
                        </button>
                      </div>
                      {u.unread_count > 0 && (
                        <span className="text-[10px] font-bold text-red-600">[{u.unread_count}]</span>
                      )}
                    </div>
                    <div className="text-[10px] text-gray-500 truncate font-mono">{u.last_message}</div>
                    <div className="text-[9px] text-gray-400 mt-1 text-right">
                      {new Date(u.last_at).toLocaleDateString()}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className={`flex-1 flex flex-col bg-white ${!selectedFeedbackUser ? 'hidden md:flex' : 'flex'}`}>
              {!selectedFeedbackUser ? (
                <div className="flex-1 flex flex-col items-center justify-center text-gray-300">
                  <div className="text-xs font-mono">{'>'} select_thread_to_view</div>
                </div>
              ) : (
                <>
                  <div className="p-3 border-b border-gray-200 flex justify-between items-center bg-gray-50">
                    <button onClick={() => setSelectedFeedbackUser(null)} className="md:hidden text-gray-900 font-bold text-xs">
                      {'< BACK'}
                    </button>
                    <span className="text-xs font-mono text-gray-500">ID: {selectedFeedbackUser}</span>
                  </div>
                  <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    {feedbackMessages.map(msg => (
                      <div key={msg.id} className={`flex ${msg.sender === 'admin' ? 'justify-end' : 'justify-start'}`}>
                        <div className={`max-w-[85%] p-3 text-xs font-mono leading-relaxed border ${
                          msg.sender === 'admin' 
                            ? 'bg-gray-50 border-gray-900 text-gray-900' 
                            : 'bg-white border-gray-200 text-gray-600'
                        }`}>
                          <div className="mb-1 text-[9px] text-gray-400 uppercase">
                            {msg.sender === 'admin' ? 'sys_admin' : 'user'} :: {new Date(msg.created_at).toLocaleTimeString()}
                          </div>
                          {msg.content}
                        </div>
                      </div>
                    ))}
                    <div ref={feedbackScrollRef} />
                  </div>
                  <div className="p-3 border-t border-gray-200">
                    <div className="flex gap-0 border border-gray-300">
                      <input 
                        value={replyInput}
                        onChange={e => setReplyInput(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && sendReply()}
                        className="flex-1 px-3 py-2 bg-transparent border-none focus:outline-none text-xs font-mono"
                        placeholder="type_message..."
                      />
                      <button onClick={sendReply} className="px-4 py-2 bg-gray-900 text-white text-xs font-bold hover:bg-black uppercase">
                        send
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {/* Redemptions Tab */}
        {activeTab === 'redemptions' && (
          <div className="space-y-6">
            
            {/* Generate Tool */}
            <div className="border border-gray-300 p-4 bg-gray-50">
              <div className="flex justify-between items-center mb-4">
                <h3 className="font-bold text-gray-900 text-xs uppercase">[ 卡密生成工具 / GENERATOR ]</h3>
                <button 
                  onClick={() => setShowGenForm(!showGenForm)}
                  className="text-xs text-gray-500 hover:text-gray-900 underline"
                >
                  {showGenForm ? '隐藏 / HIDE' : '展开 / EXPAND'}
                </button>
              </div>
              
              {showGenForm && (
                <div className="space-y-4">
                  {/* Guide */}
                  <div className="text-[10px] text-gray-500 bg-white border border-gray-200 p-3 mb-4 font-mono leading-relaxed">
                    <p className="font-bold mb-1">📝 操作指南 / GUIDE:</p>
                    <ul className="list-disc pl-4 space-y-1">
                      <li><b>会员等级 (TIER)</b> 决定数据保留时长：S1=3个月, S2=12个月, S5=永久。</li>
                      <li><b>加油包 (ADDON)</b>：请选择类型为 ADDON，并留空会员等级和时长，仅填写 Token 和券。</li>
                      <li><b>会员卡 (SUB)</b>：需填写等级 (TIER) 和时长 (DAYS)，以及包含的资源。</li>
                      <li><b>批次号 (BATCH)</b>：建议使用自动生成的 ID，方便后续按批次导出或作废。</li>
                    </ul>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <label className="block text-[10px] text-gray-400 mb-1">批次号 / BATCH_ID</label>
                      <input 
                        value={genConfig.batch_id}
                        onChange={e => setGenConfig({...genConfig, batch_id: e.target.value})}
                        className="w-full px-2 py-1.5 border border-gray-300 text-xs font-mono"
                        placeholder="BATCH_..."
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] text-gray-400 mb-1">类型 / TYPE</label>
                      <select 
                        value={genConfig.card_type}
                        onChange={e => setGenConfig({...genConfig, card_type: e.target.value})}
                        className="w-full px-2 py-1.5 border border-gray-300 text-xs font-mono"
                      >
                        <option value="trial_pack">试用包 / TRIAL</option>
                        <option value="subscription_pack">订阅会员 / SUB</option>
                        <option value="addon_pack">加油包 / ADDON</option>
                        <option value="report_coupon">仅报告券 / COUPON</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-[10px] text-gray-400 mb-1">会员等级 / TIER</label>
                      <select 
                        value={genConfig.target_tier}
                        onChange={e => setGenConfig({...genConfig, target_tier: e.target.value})}
                        className="w-full px-2 py-1.5 border border-gray-300 text-xs font-mono"
                      >
                        <option value="">无 (仅资源) / NONE</option>
                        <option value="S1">S1 基础版 (3月保留)</option>
                        <option value="S2">S2 高级版 (12月保留)</option>
                        <option value="S5">S5 至尊版 (永久保留)</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-[10px] text-gray-400 mb-1">CP 数量 / CP_AMOUNT</label>
                      <div className="flex items-center gap-2">
                        <input 
                          type="number"
                          value={genConfig.cp_multiplier}
                          onChange={e => setGenConfig({...genConfig, cp_multiplier: Number(e.target.value)})}
                          className="flex-1 px-2 py-1.5 border border-gray-300 text-xs font-mono"
                          min="0"
                          placeholder="e.g. 1000"
                        />
                        <span className="text-[10px] text-gray-500 font-mono whitespace-nowrap bg-gray-100 px-1 py-0.5 rounded">
                          ≈{((genConfig.cp_multiplier || 0) * 12400 / 1000000).toFixed(2)}M BT
                        </span>
                      </div>
                    </div>
                    <div>
                      <label className="block text-[10px] text-gray-400 mb-1">报告券 / COUPONS</label>
                      <input 
                        type="number"
                        value={genConfig.coupon_amount}
                        onChange={e => setGenConfig({...genConfig, coupon_amount: Number(e.target.value)})}
                        className="w-full px-2 py-1.5 border border-gray-300 text-xs font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] text-gray-400 mb-1">会员天数 / DAYS</label>
                      <input 
                        type="number"
                        value={genConfig.premium_days}
                        onChange={e => setGenConfig({...genConfig, premium_days: Number(e.target.value)})}
                        className="w-full px-2 py-1.5 border border-gray-300 text-xs font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] text-gray-400 mb-1">卡密有效期 / EXPIRES</label>
                      <input 
                        type="number"
                        value={genConfig.expires_days}
                        onChange={e => setGenConfig({...genConfig, expires_days: Number(e.target.value)})}
                        className="w-full px-2 py-1.5 border border-gray-300 text-xs font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] text-gray-400 mb-1">生成数量 / COUNT</label>
                      <input 
                        type="number"
                        value={genConfig.count}
                        onChange={e => setGenConfig({...genConfig, count: Number(e.target.value)})}
                        className="w-full px-2 py-1.5 border border-gray-300 text-xs font-mono"
                      />
                    </div>
                  </div>
                  
                  <div className="flex gap-2">
                    <button 
                      onClick={handleGenerateCards}
                      disabled={generating}
                      className="px-4 py-2 bg-gray-900 text-white text-xs font-bold hover:bg-black transition-all"
                    >
                      {generating ? 'PROCESSING...' : '[ 生成卡密 / EXECUTE ]'}
                    </button>
                  </div>

                  {generatedCodes.length > 0 && (
                    <div className="mt-4 p-4 bg-white border border-gray-200">
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-xs font-bold text-green-700">生成成功 / SUCCESS: {generatedCodes.length}</span>
                        <button onClick={downloadCSV} className="text-xs text-blue-600 hover:underline">
                          [ 导出 CSV / DOWNLOAD ]
                        </button>
                      </div>
                      <div className="max-h-32 overflow-y-auto text-[10px] font-mono text-gray-500 space-y-1">
                        {generatedCodes.map(c => <div key={c}>{c}</div>)}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* View Switcher */}
            <div className="flex justify-between items-end border-b border-gray-200 pb-2">
              <div className="flex gap-4">
                <button
                  onClick={() => setRedemptionView('list')}
                  className={`text-xs font-bold pb-1 ${redemptionView === 'list' ? 'text-gray-900 border-b-2 border-gray-900' : 'text-gray-400'}`}
                >
                  卡片列表 / CARDS
                </button>
                <button
                  onClick={() => setRedemptionView('batch')}
                  className={`text-xs font-bold pb-1 ${redemptionView === 'batch' ? 'text-gray-900 border-b-2 border-gray-900' : 'text-gray-400'}`}
                >
                  批次管理 / BATCHES
                </button>
              </div>
              <div className="flex gap-2">
                <input
                  placeholder="search_code..."
                  className="w-40 px-2 py-1 border border-gray-300 focus:border-gray-900 focus:outline-none text-xs font-mono"
                />
                <button onClick={() => { mutateRedemptions(); mutateBatches(); }} className="px-3 py-1 border border-gray-300 hover:border-gray-900 text-xs font-bold transition-all uppercase">
                  刷新 / REFRESH
                </button>
              </div>
            </div>
            
            {/* List View */}
            {redemptionView === 'list' && (
              <>
                {selectedCodes.size > 0 && (
                  <div className="bg-gray-100 p-2 flex items-center justify-between animate-in fade-in slide-in-from-top-1">
                    <span className="text-xs font-bold ml-2">已选: {selectedCodes.size}</span>
                    <div className="flex gap-2">
                      <button onClick={() => handleBulkUpdate('disabled')} className="px-3 py-1 bg-red-600 text-white text-xs font-bold hover:bg-red-700">
                        [ 批量禁用 / DISABLE ]
                      </button>
                      <button onClick={() => handleBulkUpdate('active')} className="px-3 py-1 border border-green-600 text-green-700 text-xs font-bold hover:bg-green-50">
                        [ 批量启用 / ENABLE ]
                      </button>
                    </div>
                  </div>
                )}

                {redemptionsLoading && !showGenForm ? (
                  <div className="py-8 text-gray-400 text-xs font-mono">{'>'} loading_data...</div>
                ) : redemptions.length === 0 ? (
                  <div className="py-8 text-gray-400 text-xs font-mono">{'>'} no_data</div>
                ) : (
                  <div className="border border-gray-200">
                    <table className="w-full text-left text-xs font-mono">
                      <thead className="bg-gray-50 border-b border-gray-200 text-gray-500">
                        <tr>
                          <th className="p-3 w-10">
                            <input 
                              type="checkbox" 
                              onChange={(e) => {
                                if (e.target.checked) setSelectedCodes(new Set(redemptions.map(r => r.code)));
                                else setSelectedCodes(new Set());
                              }}
                              checked={selectedCodes.size === redemptions.length && redemptions.length > 0}
                            />
                          </th>
                          <th className="p-3 font-bold">卡密 / CODE</th>
                          <th className="p-3 font-bold">批次 / BATCH</th>
                          <th className="p-3 font-bold">状态 / STATUS</th>
                          <th className="p-3 font-bold text-right">面额 / VALUE</th>
                          <th className="p-3 font-bold">兑换人 / REDEEMED_BY</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {redemptions.map((r) => (
                          <tr key={r.id} className="hover:bg-gray-50 group">
                            <td className="p-3">
                              <input 
                                type="checkbox"
                                checked={selectedCodes.has(r.code)}
                                onChange={(e) => {
                                  const next = new Set(selectedCodes);
                                  if (e.target.checked) next.add(r.code);
                                  else next.delete(r.code);
                                  setSelectedCodes(next);
                                }}
                              />
                            </td>
                            <td className="p-3 font-bold text-gray-900 select-all font-mono">{r.code}</td>
                            <td className="p-3 text-gray-500 font-mono text-[10px]">{r.batch_id || '-'}</td>
                            <td className="p-3">
                              <span className={`px-1.5 py-0.5 text-[10px] border ${
                                r.status === 'active' ? 'border-green-600 text-green-700' :
                                r.status === 'redeemed' ? 'border-gray-300 text-gray-400 line-through' : 'border-red-600 text-red-700'
                              }`}>
                                {r.status.toUpperCase()}
                              </span>
                            </td>
                            <td className="p-3 text-right">
                              <div className="text-gray-900">BT: {r.bt_amount}</div>
                              <div className="text-gray-500">CPN: {r.report_coupons || r.coupon_amount || 0}</div>
                              {r.premium_days > 0 && <div className="text-gray-500">DAY: {r.premium_days}</div>}
                              {(r.plan_tier || r.meta?.target_tier) && <div className="text-gray-500 font-bold">{r.plan_tier || r.meta?.target_tier}</div>}
                            </td>
                            <td className="p-3 text-gray-500">
                              {r.redeemed_by ? (
                                <div>
                                  <div>{r.redeemed_by.slice(0, 8)}...</div>
                                  <div className="text-[9px]">{r.redeemed_at ? new Date(r.redeemed_at).toLocaleDateString() : '-'}</div>
                                </div>
                              ) : '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}

            {/* Batch View */}
            {redemptionView === 'batch' && (
              <div className="border border-gray-200">
                <table className="w-full text-left text-xs font-mono">
                  <thead className="bg-gray-50 border-b border-gray-200 text-gray-500">
                    <tr>
                      <th className="p-3 font-bold">批次号 / BATCH_ID</th>
                      <th className="p-3 font-bold">创建时间 / CREATED_AT</th>
                      <th className="p-3 font-bold text-right">总量 / TOTAL</th>
                      <th className="p-3 font-bold text-right">待兑换 / ACTIVE</th>
                      <th className="p-3 font-bold text-right">已兑换 / REDEEMED</th>
                      <th className="p-3 font-bold text-right">操作 / ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {batches.map((b) => (
                      <tr key={b.batch_id} className="hover:bg-gray-50">
                        <td className="p-3 font-bold text-gray-900">{b.batch_id}</td>
                        <td className="p-3 text-gray-500">{new Date(b.created_at).toLocaleString()}</td>
                        <td className="p-3 text-right font-bold">{b.total_count}</td>
                        <td className="p-3 text-right text-green-700">{b.active_count}</td>
                        <td className="p-3 text-right text-gray-400">{b.redeemed_count}</td>
                        <td className="p-3 text-right">
                          <button 
                            onClick={() => handleDisableBatch(b.batch_id)}
                            className="text-red-600 hover:underline font-bold"
                          >
                            [ 作废本批次 / DISABLE ]
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Submissions Tab */}
        {activeTab === 'submissions' && (
          <div>
            {viewMode === 'list' ? (
              <div className="space-y-4">
                {users.length === 0 ? (
                  <div className="py-12 text-gray-400 text-xs font-mono">{'>'} no_data_loaded</div>
                ) : (
                  <div className="border border-gray-200">
                    {users.map((item, idx) => {
                      const u = item.user;
                      const w = item.wallet;
                      return (
                        <div key={u.user_id} className={`p-3 flex items-center justify-between hover:bg-gray-50 ${idx !== users.length - 1 ? 'border-b border-gray-100' : ''}`}>
                          <div>
                            <div className="font-bold text-gray-900">{u.phone}</div>
                            <div className="text-[10px] text-gray-500 font-mono mt-0.5">
                              PLAN:{w?.plan_tier?.toUpperCase() || 'FREE'} | BT:{((w?.bt_trial || 0) + (w?.bt_subscription || 0))}
                            </div>
                          </div>
                          <button
                            onClick={() => handleSelectUser(u.user_id)}
                            className="px-3 py-1 text-[10px] border border-gray-300 hover:border-gray-900 hover:text-gray-900 uppercase transition-all"
                          >
                            [ 查看 / INSPECT ]
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : (
              <>
                <button
                  onClick={handleBackToList}
                  className="mb-6 text-xs font-bold text-gray-500 hover:text-gray-900 hover:underline uppercase"
                >
                  {'< Return to list'}
                </button>

                <div className="border border-gray-200 p-4 mb-6 bg-gray-50">
                  <div className="text-xl font-bold text-gray-900 font-mono">
                    USER :: {users.find((u) => u.user.user_id === selectedUser)?.user.phone}
                  </div>
                  <div className="text-xs font-mono text-gray-400 mt-1">
                    UUID: {selectedUser}
                  </div>
                </div>

                {/* Sub-Tab Navigation */}
                <div className="flex border-b border-gray-200 mb-6">
                  {[
                    { key: 'submissions' as const, label: 'SUBMISSIONS', count: userSubmissions.length },
                    { key: 'reports' as const, label: 'REPORTS', count: userReports.length },
                    { key: 'ledger' as const, label: 'LEDGER', count: usageLedger.length }
                  ].map((tab) => (
                    <button
                      key={tab.key}
                      onClick={() => setSubTab(tab.key)}
                      className={`px-4 py-2 text-xs font-bold border-b-2 transition-all ${
                        subTab === tab.key
                          ? 'border-gray-900 text-gray-900'
                          : 'border-transparent text-gray-400 hover:text-gray-600'
                      }`}
                    >
                      {tab.label} <span className="opacity-50">[{tab.count}]</span>
                    </button>
                  ))}
                </div>

                {/* Submissions Content */}
                {subTab === 'submissions' && (
                  <div className="space-y-2">
                    {userSubmissions.map((item) => (
                      <div key={item.submission_id} className="border border-gray-200 p-3 hover:border-gray-400 transition-colors">
                        <div className="flex justify-between items-start">
                          <div>
                            <div className="font-bold text-gray-900 text-sm">{item.subject?.toUpperCase() || 'MATH'}</div>
                            <div className="text-[10px] text-gray-400 font-mono mt-1">
                              ID: {item.submission_id}
                            </div>
                          </div>
                          <div className="text-[10px] text-gray-500 font-mono">
                            {new Date(item.created_at).toLocaleString()}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Reports Content */}
                {subTab === 'reports' && (
                  <div className="space-y-2">
                    {userReports.map((item) => (
                      <div key={item.id} className="border border-gray-200 p-3 hover:border-gray-400">
                        <div className="font-bold text-gray-900 text-sm">{item.title || 'REPORT'}</div>
                        <div className="text-[10px] text-gray-500 font-mono mt-1">
                          {new Date(item.period_from).toLocaleDateString()} {'->'} {new Date(item.period_to).toLocaleDateString()}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Usage Ledger Content */}
                {subTab === 'ledger' && (
                  <div className="border border-gray-200">
                    <table className="w-full text-left text-xs font-mono">
                      <thead className="bg-gray-50 text-gray-500 border-b border-gray-200">
                        <tr>
                          <th className="p-2">EVENT</th>
                          <th className="p-2 text-right">CHANGE</th>
                          <th className="p-2 text-right">BALANCE</th>
                          <th className="p-2 text-right">TIME</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {usageLedger.map((item, idx) => (
                          <tr key={idx} className="hover:bg-gray-50">
                            <td className="p-2 text-gray-900 font-bold">{item.event_type}</td>
                            <td className={`p-2 text-right font-bold ${item.amount_delta < 0 ? 'text-gray-900' : 'text-gray-500'}`}>
                              {item.amount_delta > 0 ? '+' : ''}{item.amount_delta}
                            </td>
                            <td className="p-2 text-right text-gray-500">{item.balance_after}</td>
                            <td className="p-2 text-right text-gray-400 text-[10px]">{new Date(item.created_at).toLocaleTimeString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Audit Logs Tab */}
        {activeTab === 'audit' && (
          <div>
            {auditLoading ? (
              <div className="text-gray-400 text-xs font-mono">{'>'} fetching_logs...</div>
            ) : (
              <div className="font-mono text-xs border border-gray-200 bg-gray-50 p-4 overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="text-gray-400 border-b border-gray-300">
                    <tr>
                      <th className="pb-2 font-normal">TIMESTAMP</th>
                      <th className="pb-2 font-normal">ACTION</th>
                      <th className="pb-2 font-normal">ACTOR</th>
                      <th className="pb-2 font-normal">TARGET</th>
                      <th className="pb-2 font-normal">PAYLOAD</th>
                    </tr>
                  </thead>
                  <tbody className="text-gray-700">
                    {auditLogs.map((log) => (
                      <tr key={log.request_id} className="align-top hover:bg-gray-100 transition-colors border-b border-gray-200 last:border-0">
                        <td className="py-2 pr-4 text-gray-500 whitespace-nowrap">{new Date(log.created_at).toLocaleString()}</td>
                        <td className="py-2 pr-4 font-bold text-gray-900 uppercase">{log.action}</td>
                        <td className="py-2 pr-4">{log.actor || 'SYSTEM'}</td>
                        <td className="py-2 pr-4 text-gray-600">{log.target_type}</td>
                        <td className="py-2 text-gray-500 max-w-md truncate cursor-help" title={JSON.stringify(log.payload, null, 2)}>
                          {JSON.stringify(log.payload)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default Admin;
