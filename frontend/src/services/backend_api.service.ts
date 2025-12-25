/**
 * Minimal client for the FastAPI backend.
 */

import { makeObservable } from "mobx";

import { LoadingStatus } from "../shared/lumi_doc";
import { LumiAnswer, LumiAnswerRequest, UserFeedback } from "../shared/api";
import { Service } from "./service";

const API_BASE_URL =
  (typeof process !== "undefined" &&
    process.env.API_BASE_URL &&
    process.env.API_BASE_URL.replace(/\/+$/, "")) ||
  "";

export interface RequestImportResponse {
  job_id: string;
  arxiv_id: string;
  version?: string;
  status: LoadingStatus | string;
}

export interface JobStatusResponse {
  job_id: string;
  status: LoadingStatus | string;
  arxiv_id: string;
  version?: string;
  stage?: string;
  progress_percent?: number;
}

export interface MetadataResponse {
  arxiv_id: string;
  metadata: any;
}

export interface LumiDocResponse {
  arxiv_id: string;
  version: string;
  doc: any;
  summaries: any;
}

export interface LumiDocSectionResponse {
  arxiv_id: string;
  version: string;
  section: any;
}

export interface ListPapersResponse {
  papers: { arxiv_id: string; version: string; metadata?: any }[];
}

export interface ArxivSearchPaper {
  metadata: any;
  score?: number | null;
}

export interface ArxivSearchResponse {
  papers: ArxivSearchPaper[];
  total: number;
  page: number;
  page_size: number;
}

type HttpMethod = "GET" | "POST";

export class BackendApiService extends Service {
  constructor() {
    super();
    makeObservable(this);
  }

  private readonly signUrlCache = new Map<string, { url: string; expiresAt: number }>();

  override initialize(): void {
    this.setInitialized();
  }

  private url(path: string) {
    return `${API_BASE_URL}${path}`;
  }

  private async request<T>(
    path: string,
    method: HttpMethod,
    body?: Record<string, unknown>
  ): Promise<T> {
    const resp = await fetch(this.url(path), {
      method,
      headers: {
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`HTTP ${resp.status}: ${text || resp.statusText}`);
    }
    return (await resp.json()) as T;
  }

  async requestImport(arxivId: string): Promise<RequestImportResponse> {
    return this.request("/api/request_arxiv_doc_import", "POST", {
      arxiv_id: arxivId,
    });
  }

  async requestLocalPdfImport(
    file: File,
    title?: string
  ): Promise<RequestImportResponse> {
    const formData = new FormData();
    formData.append("file", file);
    if (title) {
      formData.append("title", title);
    }
    const resp = await fetch(this.url("/api/request_local_pdf_import"), {
      method: "POST",
      body: formData,
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`HTTP ${resp.status}: ${text || resp.statusText}`);
    }
    return (await resp.json()) as RequestImportResponse;
  }

  async jobStatus(jobId: string): Promise<JobStatusResponse> {
    return this.request(`/api/job-status/${jobId}`, "GET");
  }

  async getMetadata(arxivId: string): Promise<MetadataResponse> {
    return this.request("/api/get_arxiv_metadata", "POST", { arxiv_id: arxivId });
  }

  async getLumiDoc(arxivId: string, version: string): Promise<LumiDocResponse> {
    return this.request(`/api/lumi-doc/${arxivId}/${version}`, "GET");
  }

  async getLumiDocIndex(
    arxivId: string,
    version: string
  ): Promise<LumiDocResponse> {
    return this.request(`/api/lumi-doc-index/${arxivId}/${version}`, "GET");
  }

  async getLumiDocSection(
    arxivId: string,
    version: string,
    sectionId: string
  ): Promise<LumiDocSectionResponse> {
    return this.request(
      `/api/lumi-doc-section/${arxivId}/${version}/${sectionId}`,
      "GET"
    );
  }

  async getLumiResponse(
    arxivId: string,
    version: string,
    request: LumiAnswerRequest
  ): Promise<LumiAnswer> {
    return this.request("/api/get_lumi_response", "POST", {
      arxiv_id: arxivId,
      version,
      ...request,
    });
  }

  async getPersonalSummary(
    arxivId: string,
    version: string,
    pastPapers: any[]
  ): Promise<LumiAnswer> {
    return this.request("/api/get_personal_summary", "POST", {
      arxiv_id: arxivId,
      version,
      past_papers: pastPapers,
    });
  }

  async listPapers(): Promise<ListPapersResponse> {
    return this.request("/api/list-papers", "GET");
  }

  async listArxivRecent(
    page: number,
    pageSize: number,
    categories?: string[]
  ): Promise<ArxivSearchResponse> {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (categories && categories.length > 0) {
      params.set("categories", categories.join(","));
    }
    return this.request(`/api/arxiv-sanity/recent?${params.toString()}`, "GET");
  }

  async searchArxivPapers(
    query: string,
    page: number,
    pageSize: number,
    categories?: string[]
  ): Promise<ArxivSearchResponse> {
    const params = new URLSearchParams({
      query,
      page: String(page),
      page_size: String(pageSize),
    });
    if (categories && categories.length > 0) {
      params.set("categories", categories.join(","));
    }
    return this.request(`/api/arxiv-sanity/search?${params.toString()}`, "GET");
  }

  async saveUserFeedback(feedback: UserFeedback): Promise<void> {
    await this.request("/api/save_user_feedback", "POST", {
      user_feedback_text: feedback.userFeedbackText,
      arxiv_id: feedback.arxivId,
    });
  }

  async signUrl(path: string, op: "get" | "put" = "get"): Promise<string> {
    const cacheKey = `${op}:${path}`;
    const cached = this.signUrlCache.get(cacheKey);
    const now = Date.now();
    if (cached && cached.expiresAt > now) {
      return cached.url;
    }

    const resp = await fetch(
      this.url(`/api/sign-url?path=${encodeURIComponent(path)}&op=${op}`),
      {
        method: "GET",
      }
    );
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`HTTP ${resp.status}: ${text || resp.statusText}`);
    }
    const data = (await resp.json()) as { url: string };
    // Presigned URLs default to 1 hour; refresh a bit early.
    this.signUrlCache.set(cacheKey, {
      url: data.url,
      expiresAt: now + 55 * 60 * 1000,
    });
    return data.url;
  }
}
