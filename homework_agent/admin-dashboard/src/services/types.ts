export type JobStatus = 'queued' | 'pending' | 'processing' | 'running' | 'done' | 'failed';
export type CardState = 'placeholder' | 'verdict_ready' | 'review_pending' | 'review_ready' | 'review_failed';
export type Verdict = 'correct' | 'incorrect' | 'uncertain';
export type AnswerState = 'blank' | 'has_answer' | 'unknown';

export interface QuestionCard {
    item_id: string;
    question_number: string;
    page_index: number;
    answer_state?: AnswerState;
    question_content?: string;
    question_slice_image_url?: string;
    figure_slice_image_url?: string;
    image_refs?: Record<string, any>;
    visual_risk?: boolean;
    visual_risk_reasons?: string[];
    card_state?: CardState;
    verdict?: Verdict;
    reason?: string;
    needs_review?: boolean;
    review_summary?: string;
    review_reasons?: string[];
    review_slice_image_url?: string;
    review_bbox?: number[];
}

export interface PageSummary {
    page_index: number;
    wrong_count?: number;
    uncertain_count?: number;
    blank_count?: number;
    needs_review?: boolean;
}

export interface JobResponse {
    job_id: string;
    status: JobStatus;
    result?: any;
    error?: string | null;
    created_at?: string;
    updated_at?: string;
    elapsed_ms?: number;
    total_pages?: number;
    done_pages?: number;
    page_summaries?: PageSummary[];
    question_cards?: QuestionCard[];
    submission_id?: string;
    session_id?: string;
}

export interface SubmissionSummary {
    total_items?: number;
    wrong_count?: number;
    uncertain_count?: number;
    blank_count?: number;
    score_text?: string;
}

export interface SubmissionItem {
    submission_id: string;
    profile_id?: string | null;
    created_at?: string;
    subject?: string;
    total_pages?: number;
    done_pages?: number;
    session_id?: string;
    summary?: SubmissionSummary;
}

export interface SubmissionDetail extends SubmissionItem {
    page_image_urls?: string[];
    vision_raw_text?: string;
    page_summaries?: PageSummary[];
    question_cards?: QuestionCard[];
    questions?: Array<Record<string, any>>;
}

export interface QuotaResponse {
    cp_left: number;
    report_coupons_left: number;
    trial_expires_at?: string | null;
    plan_tier?: string | null;
    data_retention_tier?: string | null;
}

export interface ProfileItem {
    profile_id: string;
    display_name: string;
    avatar_url?: string | null;
    is_default?: boolean;
    created_at?: string | null;
}

export interface ProfilesResponse {
    default_profile_id: string;
    profiles: ProfileItem[];
}

export interface MistakeItem {
    submission_id: string;
    session_id?: string;
    subject?: string;
    created_at?: string;
    item_id: string;
    question_number?: string;
    reason?: string;
    severity?: string;
    knowledge_tags?: string[];
    raw?: Record<string, any>;
}

export interface MistakeListResponse {
    items: MistakeItem[];
    next_before_created_at?: string | null;
}

export interface ReportEligibility {
    eligible: boolean;
    submission_count: number;
    required_count: number;
    distinct_days: number;
    required_days: number;
    subject?: string;
    reason?: string;
    progress_percent?: number;
    sample_submission_ids?: string[];
}

export interface ReportJob {
    job_id?: string;
    status?: string;
    report_id?: string;
    error?: string;
    created_at?: string;
    updated_at?: string;
}

export interface ReportListItem {
    report_id: string;
    created_at?: string;
    subject?: string;
    title?: string;
    params?: Record<string, any>;
}

export interface ReportListResponse {
    items: ReportListItem[];
}

export interface ReportContent {
    report_id: string;
    content?: string;
    title?: string;
    stats?: Record<string, any>;
    params?: Record<string, any>;
    created_at?: string;
}

// ============================================================================
// Admin Types
// ============================================================================

export interface AdminUser {
    user_id: string;
    phone: string;
    created_at?: string;
    last_login_at?: string;
}

export interface WalletInfo {
    user_id: string;
    bt_trial: number;
    bt_subscription: number;
    bt_report_reserve: number;
    report_coupons: number;
    trial_expires_at?: string;
    plan_tier?: string;
    data_retention_tier?: string;
    updated_at?: string;
}

export interface AdminUserDetail {
    user: AdminUser;
    wallet?: WalletInfo;
}

export interface AuditLogItem {
    actor: string;
    action: string;
    target_type: string;
    target_id: string | null;
    payload: Record<string, any>;
    request_id: string;
    ip: string;
    user_agent: string;
    created_at: string;
}

export interface AdminSubmissionItem {
    submission_id: string;
    user_id: string;
    profile_id?: string;
    created_at: string;
    subject?: string;
    session_id: string;
    warnings?: any[];
}

export interface AdminReportItem {
    id: string;
    user_id: string;
    profile_id?: string;
    report_job_id: string;
    title: string;
    period_from: string;
    period_to: string;
    created_at: string;
}

export interface UsageLedgerItem {
    id: string;
    user_id: string;
    event_type: string;
    amount_delta: number;
    balance_after: number;
    created_at: string;
}
