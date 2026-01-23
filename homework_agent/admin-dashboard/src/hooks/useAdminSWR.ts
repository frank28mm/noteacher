import useSWR from 'swr';
import { apiClient } from '@/services/api';
import type {
  AdminUserDetail,
  AuditLogItem,
  AdminSubmissionItem,
  AdminReportItem,
  UsageLedgerItem
} from '@/services/types';

export interface DashboardStats {
  kpi: {
    total_users: number;
    paid_ratio: string;
    dau: number;
    mrr: string;
  };
  cost: {
    tokens_today: string;
    subs_today: number;
    avg_cost: string;
  };
  conversion: {
    card_redemption_rate: string;
    trial_conversion: string;
  };
  health: {
    error_rate: string;
    latency_p50: string;
  };
}

export interface FeedbackUser {
  user_id: string;
  unread_count: number;
  last_message: string;
  last_at: string;
}

export interface FeedbackMessage {
  id: string;
  sender: 'user' | 'admin';
  content: string;
  created_at: string;
}

export interface RedemptionItem {
  id: string;
  code: string;
  batch_id: string;
  status: 'active' | 'redeemed' | 'disabled';
  bt_amount: number;
  coupon_amount: number;
  report_coupons: number;
  premium_days: number;
  plan_tier?: string;
  meta?: { target_tier?: string };
  redeemed_by?: string;
  redeemed_at?: string;
}

export interface BatchItem {
  batch_id: string;
  created_at: string;
  total_count: number;
  active_count: number;
  redeemed_count: number;
}

const createAdminFetcher = (token: string) => async (url: string) => {
  const res = await apiClient.get(url, {
    headers: { 'X-Admin-Token': token }
  });
  return res.data;
};

export function useDashboard(token: string | null) {
  return useSWR<DashboardStats>(
    token ? '/admin/stats/dashboard' : null,
    token ? createAdminFetcher(token) : null,
    {
      revalidateOnFocus: true,
      dedupingInterval: 30000,
    }
  );
}

export function useUsers(token: string | null, searchPhone?: string) {
  const key = token ? ['/admin/users', searchPhone || ''] : null;
  
  return useSWR<{ users: AdminUserDetail[] }>(
    key,
    async ([url]) => {
      const res = await apiClient.get(url, {
        headers: { 'X-Admin-Token': token! },
        params: { 
          phone: searchPhone || undefined,
          include_wallet: true
        },
      });
      return res.data;
    },
    {
      revalidateOnFocus: false,
      dedupingInterval: 10000,
    }
  );
}

export function useFeedbackUsers(token: string | null) {
  return useSWR<{ items: FeedbackUser[] }>(
    token ? '/admin/feedback/users' : null,
    token ? createAdminFetcher(token) : null,
    {
      revalidateOnFocus: true,
      dedupingInterval: 5000,
    }
  );
}

export function useFeedbackMessages(token: string | null, userId: string | null) {
  return useSWR<{ messages: FeedbackMessage[] }>(
    token && userId ? `/admin/feedback/${userId}` : null,
    async (url) => {
      const res = await apiClient.get(url, {
        headers: { 'X-Admin-Token': token! },
        params: { limit: 100 }
      });
      return res.data;
    },
    {
      refreshInterval: 5000,
      revalidateOnFocus: true,
    }
  );
}

export function useRedemptions(token: string | null) {
  return useSWR<{ items: RedemptionItem[] }>(
    token ? '/admin/redemptions' : null,
    async (url) => {
      const res = await apiClient.get(url, {
        headers: { 'X-Admin-Token': token! },
        params: { limit: 50 }
      });
      return res.data;
    },
    {
      revalidateOnFocus: false,
      dedupingInterval: 10000,
    }
  );
}

export function useBatches(token: string | null) {
  return useSWR<{ items: BatchItem[] }>(
    token ? '/admin/redeem_cards/batches' : null,
    token ? createAdminFetcher(token) : null,
    {
      revalidateOnFocus: false,
      dedupingInterval: 10000,
    }
  );
}

export function useAuditLogs(token: string | null) {
  return useSWR<{ items: AuditLogItem[] }>(
    token ? '/admin/audit_logs' : null,
    async (url) => {
      const res = await apiClient.get(url, {
        headers: { 'X-Admin-Token': token! },
        params: { limit: 50 }
      });
      return res.data;
    },
    {
      revalidateOnFocus: true,
      dedupingInterval: 30000,
    }
  );
}

export function useUserSubmissions(token: string | null, userId: string | null) {
  return useSWR<{ items: AdminSubmissionItem[] }>(
    token && userId ? ['/admin/submissions', userId] : null,
    async ([url]) => {
      const res = await apiClient.get(url, {
        headers: { 'X-Admin-Token': token! },
        params: { user_id: userId, limit: 50 }
      });
      return res.data;
    },
    {
      revalidateOnFocus: false,
    }
  );
}

export function useUserReports(token: string | null, userId: string | null) {
  return useSWR<{ items: AdminReportItem[] }>(
    token && userId ? ['/admin/reports', userId] : null,
    async ([url]) => {
      const res = await apiClient.get(url, {
        headers: { 'X-Admin-Token': token! },
        params: { user_id: userId, limit: 50 }
      });
      return res.data;
    },
    {
      revalidateOnFocus: false,
    }
  );
}

export function useUsageLedger(token: string | null, userId: string | null) {
  return useSWR<{ items: UsageLedgerItem[] }>(
    token && userId ? ['/admin/usage_ledger', userId] : null,
    async ([url]) => {
      const res = await apiClient.get(url, {
        headers: { 'X-Admin-Token': token! },
        params: { user_id: userId, limit: 50 }
      });
      return res.data;
    },
    {
      revalidateOnFocus: false,
    }
  );
}
