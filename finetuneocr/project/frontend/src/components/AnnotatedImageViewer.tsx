import React, { useState } from 'react';
import type { ExtractedField, ComplianceCheck, OCRResult } from '../types';

interface AnnotatedImageViewerProps {
  annotatedImage: string;
  originalImage: string;
  fields: ExtractedField[];
  checks: ComplianceCheck[];
  ocrResults: OCRResult[];
}

/** Backend now sends data URLs, but tolerate raw base64 too. */
function toDataUrl(maybeB64: string): string {
  if (!maybeB64) return '';
  if (maybeB64.startsWith('data:') || maybeB64.startsWith('blob:') || maybeB64.startsWith('http')) {
    return maybeB64;
  }
  return `data:image/jpeg;base64,${maybeB64}`;
}

export const AnnotatedImageViewer: React.FC<AnnotatedImageViewerProps> = ({
  annotatedImage,
  originalImage,
  fields,
  checks,
  ocrResults,
}) => {
  const [viewMode, setViewMode] = useState<'annotated' | 'original' | 'overlay'>('annotated');
  const [showOcrBoxes, setShowOcrBoxes] = useState(false);
  const [highlightedField, setHighlightedField] = useState<string | null>(null);
  const [imgSize, setImgSize] = useState({ w: 1, h: 1 });

  const annotatedSrc = toDataUrl(annotatedImage);
  const originalSrc = toDataUrl(originalImage);
  const shownSrc = viewMode === 'original' ? originalSrc : viewMode === 'annotated' ? annotatedSrc : originalSrc;

  const getFieldCheck = (fieldName: string) => checks.find((c) => c.field === fieldName);

  const getFieldColor = (fieldName: string) => {
    const check = getFieldCheck(fieldName);
    switch (check?.status) {
      case 'PASS': return '#22c55e';
      case 'FAIL': return '#ef4444';
      case 'REVIEW': return '#f59e0b';
      default: return '#3b82f6';
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
      <div className="p-4 border-b border-gray-200 flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-semibold text-gray-900">Package Image</h3>
        <div className="flex items-center gap-3 text-sm">
          <label className="inline-flex items-center gap-1.5 text-gray-600 cursor-pointer">
            <input
              type="radio"
              name="viewMode"
              checked={viewMode === 'annotated'}
              onChange={() => setViewMode('annotated')}
              className="text-primary-600 focus:ring-primary-500"
            />
            Annotated (backend boxes)
          </label>
          <label className="inline-flex items-center gap-1.5 text-gray-600 cursor-pointer">
            <input
              type="radio"
              name="viewMode"
              checked={viewMode === 'overlay'}
              onChange={() => setViewMode('overlay')}
              className="text-primary-600 focus:ring-primary-500"
            />
            Interactive overlay
          </label>
          <label className="inline-flex items-center gap-1.5 text-gray-600 cursor-pointer">
            <input
              type="radio"
              name="viewMode"
              checked={viewMode === 'original'}
              onChange={() => setViewMode('original')}
              className="text-primary-600 focus:ring-primary-500"
            />
            Original
          </label>
        </div>
        {viewMode === 'overlay' && (
          <label className="inline-flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={showOcrBoxes}
              onChange={(e) => setShowOcrBoxes(e.target.checked)}
              className="text-primary-600 focus:ring-primary-500"
            />
            Show all OCR boxes ({ocrResults.length})
          </label>
        )}
      </div>

      <div className="p-4">
        {!shownSrc ? (
          <div className="bg-gray-100 rounded-lg p-8 text-center text-gray-500">
            No image returned by backend. Check backend logs.
          </div>
        ) : (
          <div className="relative inline-block w-full">
            <img
              src={shownSrc}
              alt={viewMode === 'original' ? 'Original package image' : 'Annotated package image with OCR boxes'}
              className="w-full h-auto block rounded-lg"
              onLoad={(e) => {
                const el = e.currentTarget;
                if (el.naturalWidth) setImgSize({ w: el.naturalWidth, h: el.naturalHeight });
              }}
            />
            {viewMode === 'overlay' && (
              <div className="absolute inset-0">
                {showOcrBoxes &&
                  ocrResults.map((ocr, i) => {
                    const [x1, y1, x2, y2] = ocr.bbox;
                    return (
                      <div
                        key={`ocr-${i}`}
                        className="absolute border border-blue-500 bg-blue-500/10"
                        style={{
                          left: `${(x1 / imgSize.w) * 100}%`,
                          top: `${(y1 / imgSize.h) * 100}%`,
                          width: `${Math.max(0, (x2 - x1) / imgSize.w) * 100}%`,
                          height: `${Math.max(0, (y2 - y1) / imgSize.h) * 100}%`,
                        }}
                        title={`${ocr.text} (${Math.round(ocr.confidence * 100)}%)`}
                      />
                    );
                  })}
                {fields.map((field) => {
                  const [x1, y1, x2, y2] = field.bbox;
                  const color = getFieldColor(field.name);
                  const active = highlightedField === field.name;
                  return (
                    <div
                      key={field.name}
                      className="absolute border-2 rounded-[2px] transition-all"
                      style={{
                        left: `${(x1 / imgSize.w) * 100}%`,
                        top: `${(y1 / imgSize.h) * 100}%`,
                        width: `${Math.max(0, (x2 - x1) / imgSize.w) * 100}%`,
                        height: `${Math.max(0, (y2 - y1) / imgSize.h) * 100}%`,
                        borderColor: color,
                        backgroundColor: active ? `${color}44` : 'transparent',
                        boxShadow: active ? `0 0 0 3px ${color}` : 'none',
                      }}
                    >
                      <span
                        className="absolute -top-6 left-0 text-[11px] px-1.5 py-0.5 rounded whitespace-nowrap text-white"
                        style={{ backgroundColor: color }}
                      >
                        {field.name} ({Math.round(field.confidence * 100)}%)
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
        <p className="mt-2 text-xs text-gray-500">
          {viewMode === 'annotated'
            ? 'Boxes burned in by backend OpenCV: green = PASS, red = FAIL, yellow = REVIEW, blue = raw OCR.'
            : viewMode === 'overlay'
              ? 'Interactive boxes positioned with % coordinates — hover a pill below to spotlight a field.'
              : 'Unmodified upload straight from your device.'}
        </p>
      </div>

      <div className="p-4 border-t border-gray-200 bg-gray-50">
        <h4 className="font-medium text-gray-900 mb-2">Detected Fields (hover to highlight)</h4>
        {fields.length === 0 ? (
          <p className="text-sm text-gray-500">No fields extracted — see “What OCR actually saw” below.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {fields.map((field) => {
              const check = getFieldCheck(field.name);
              const pill =
                check?.status === 'PASS'
                  ? 'bg-green-100 text-green-700 border-green-300'
                  : check?.status === 'FAIL'
                    ? 'bg-red-100 text-red-700 border-red-300'
                    : check?.status === 'REVIEW'
                      ? 'bg-yellow-100 text-yellow-700 border-yellow-300'
                      : 'bg-blue-100 text-blue-700 border-blue-300';
              return (
                <button
                  key={field.name}
                  onMouseEnter={() => {
                    setHighlightedField(field.name);
                    if (viewMode !== 'overlay') setViewMode('overlay');
                  }}
                  onMouseLeave={() => setHighlightedField(null)}
                  onClick={() => {
                    setHighlightedField(field.name);
                    setViewMode('overlay');
                  }}
                  className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${pill}`}
                  style={
                    highlightedField === field.name
                      ? { boxShadow: `0 0 0 2px ${getFieldColor(field.name)}` }
                      : undefined
                  }
                >
                  {field.name.replace('_', ' ')}: {field.value.substring(0, 24)}
                  {field.value.length > 24 && '…'}
                </button>
              );
            })}
          </div>
        )}

        <details className="mt-4">
          <summary className="text-sm font-medium text-gray-700 cursor-pointer">
            What OCR actually saw ({ocrResults.length} regions)
          </summary>
          {ocrResults.length === 0 ? (
            <p className="text-sm text-red-600 mt-2">
              OCR returned zero text. Try a sharper, straight-on, well-lit photo filling the frame.
            </p>
          ) : (
            <ul className="mt-2 space-y-1 max-h-48 overflow-auto text-sm">
              {ocrResults.map((ocr, i) => (
                <li key={i} className="flex items-start gap-2 font-mono text-gray-700">
                  <span className="text-gray-400">[{i + 1}]</span>
                  <span className="flex-1 break-all">“{ocr.text}”</span>
                  <span className="text-gray-500">{Math.round(ocr.confidence * 100)}%</span>
                </li>
              ))}
            </ul>
          )}
        </details>
      </div>
    </div>
  );
};
