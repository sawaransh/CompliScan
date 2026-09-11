import type { AnalysisResponse, MultiAnalysisResponse } from '../types';

const API_BASE = '/api';
const MAX_IMAGES = 5;

export async function analyzeImage(file: File): Promise<AnalysisResponse> {
  const formData = new FormData();
  formData.append('image', file);

  const response = await fetch(`${API_BASE}/analyze`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Analysis failed' }));
    throw new Error(error.detail || 'Analysis failed');
  }

  return response.json();
}

export async function analyzeImages(files: File[]): Promise<MultiAnalysisResponse> {
  if (files.length === 0) throw new Error('No images selected');
  if (files.length > MAX_IMAGES) throw new Error(`Max ${MAX_IMAGES} images per product`);
  const formData = new FormData();
  files.forEach((f) => formData.append('images', f, f.name));

  const response = await fetch(`${API_BASE}/analyze-multi`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Analysis failed' }));
    throw new Error(error.detail || 'Analysis failed');
  }

  return response.json();
}

export { MAX_IMAGES };

export async function healthCheck(): Promise<{ status: string; service: string; version: string }> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error('Health check failed');
  }
  return response.json();
}