import { useState, useCallback, useEffect, useRef } from 'react';
import { FileUpload } from './components/FileUpload';
import { ProcessingSteps } from './components/ProcessingSteps';
import { AnnotatedImageViewer } from './components/AnnotatedImageViewer';
import {
  ComplianceStatusBadge,
  FieldCard,
  ChecksList,
  ViolationsList,
  ReviewItemsList,
} from './components/ResultComponents';
import { analyzeImage, analyzeImages, MAX_IMAGES } from './services/api';
import type { AnalysisResponse, MultiAnalysisResponse, ProcessingStep } from './types';

const INITIAL_STEPS: ProcessingStep[] = [
  { step: 1, name: 'Preparing images', description: 'Resizing and enhancing image quality', completed: false, active: false },
  { step: 2, name: 'Detecting text', description: 'Running OCR engines on every image', completed: false, active: false },
  { step: 3, name: 'Extracting declarations', description: 'Identifying MRP, quantity, manufacturer, dates', completed: false, active: false },
  { step: 4, name: 'Checking applicable rules', description: 'Validating merged declarations against Legal Metrology requirements', completed: false, active: false },
  { step: 5, name: 'Preparing evidence', description: 'Creating annotated images with highlights', completed: false, active: false },
];

type ResultsState =
  | { kind: 'single'; data: AnalysisResponse }
  | { kind: 'multi'; data: MultiAnalysisResponse };

function App() {
  const [stage, setStage] = useState<'upload' | 'preview' | 'processing' | 'results'>('upload');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const [processingSteps, setProcessingSteps] = useState<ProcessingStep[]>(INITIAL_STEPS);
  const [results, setResults] = useState<ResultsState | null>(null);
  const [selectedImgIdx, setSelectedImgIdx] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [elapsedSecs, setElapsedSecs] = useState<number | null>(null);
  const analyzeStartedAt = useRef<number>(0);

  // Animate the stepper while the (long, multi-engine) analysis runs,
  // so the UI reflects real progress instead of sitting on step 1.
  useEffect(() => {
    if (stage !== 'processing') return;
    let activeIdx = 0;
    setProcessingSteps(INITIAL_STEPS.map((s, i) => ({ ...s, completed: false, active: i === 0 })));
    const timer = setInterval(() => {
      activeIdx = Math.min(activeIdx + 1, INITIAL_STEPS.length - 1);
      setProcessingSteps(INITIAL_STEPS.map((s, i) => ({
        ...s,
        completed: i < activeIdx,
        active: i === activeIdx,
      })));
    }, 4000);
    return () => clearInterval(timer);
  }, [stage]);

  const handleFilesSelect = useCallback((files: File[]) => {
    setSelectedFiles((prev) => {
      const room = MAX_IMAGES - prev.length;
      if (room <= 0) {
        alert(`Max ${MAX_IMAGES} images per product`);
        return prev;
      }
      const accepted = files.slice(0, room);
      if (files.length > room) {
        alert(`Only ${room} more image(s) allowed (max ${MAX_IMAGES} per product)`);
      }
      setImageUrls((prevUrls) => [...prevUrls, ...accepted.map((f) => URL.createObjectURL(f))]);
      return [...prev, ...accepted];
    });
    setError(null);
    setStage('preview');
  }, []);

  const handleRemoveFile = useCallback((idx: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== idx));
    setImageUrls((prev) => {
      URL.revokeObjectURL(prev[idx]);
      return prev.filter((_, i) => i !== idx);
    });
  }, []);

  const handleAnalyze = useCallback(async () => {
    if (selectedFiles.length === 0) return;

    setStage('processing');
    setElapsedSecs(null);
    setSelectedImgIdx(0);
    analyzeStartedAt.current = Date.now();

    try {
      if (selectedFiles.length === 1) {
        const response = await analyzeImage(selectedFiles[0]);
        setResults({ kind: 'single', data: response });
      } else {
        const response = await analyzeImages(selectedFiles);
        setResults({ kind: 'multi', data: response });
      }

      // Update steps as completed
      setProcessingSteps(INITIAL_STEPS.map(s => ({ ...s, completed: true, active: false })));

      setElapsedSecs((Date.now() - analyzeStartedAt.current) / 1000);
      setStage('results');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed. Please try again.');
      setStage('preview');
    }
  }, [selectedFiles]);

  const handleReset = useCallback(() => {
    imageUrls.forEach((u) => URL.revokeObjectURL(u));
    setSelectedFiles([]);
    setImageUrls([]);
    setResults(null);
    setError(null);
    setElapsedSecs(null);
    setSelectedImgIdx(0);
    setStage('upload');
    setProcessingSteps(INITIAL_STEPS);
  }, [imageUrls]);

  const handleNewAnalysis = useCallback(() => {
    handleReset();
  }, [handleReset]);

  if (stage === 'upload') {
    return (
      <div className="min-h-screen bg-gray-50">
        <header className="bg-white border-b border-gray-200">
          <div className="max-w-4xl mx-auto px-4 py-6">
            <div className="text-center">
              <h1 className="text-3xl font-bold text-gray-900">CompliScan</h1>
              <p className="text-gray-600 mt-1">Packaged Commodity Compliance Scanner</p>
            </div>
          </div>
        </header>

        <main className="max-w-4xl mx-auto px-4 py-12">
          <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8">
            <div className="text-center mb-8">
              <svg className="mx-auto h-16 w-16 text-primary-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <h2 className="text-2xl font-bold text-gray-900 mt-4">Upload Product Images</h2>
              <p className="text-gray-500 mt-2">Analyze compliance with Legal Metrology (Packaged Commodities) Rules, 2011</p>
            </div>

            <FileUpload
              onFileSelect={(f) => handleFilesSelect([f])}
              onFilesSelect={handleFilesSelect}
              multiple
            />
          </div>
        </main>
      </div>
    );
  }

  if (stage === 'preview') {
    return (
      <div className="min-h-screen bg-gray-50">
        <header className="bg-white border-b border-gray-200">
          <div className="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                onClick={handleReset}
                className="p-2 text-gray-500 hover:text-gray-700 rounded-lg hover:bg-gray-100 transition-colors"
                aria-label="Back to upload"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
              </button>
              <div>
                <h1 className="text-xl font-bold text-gray-900">CompliScan</h1>
                <p className="text-sm text-gray-500">Packaged Commodity Compliance Scanner</p>
              </div>
            </div>
          </div>
        </header>

        <main className="max-w-4xl mx-auto px-4 py-8">
          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700" role="alert">
              {error}
            </div>
          )}

          <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden animate-fade-in">
            <div className="p-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">
                Product Preview ({selectedFiles.length}/{MAX_IMAGES})
              </h3>
              {selectedFiles.length < MAX_IMAGES && (
                <label className="text-sm text-primary-600 hover:text-primary-700 font-medium cursor-pointer">
                  + Add more
                  <input
                    type="file"
                    accept="image/jpeg,image/jpg,image/png,image/webp,image/heic,image/heif,.heic,.heif"
                    multiple
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files?.length) {
                        handleFilesSelect(Array.from(e.target.files));
                        e.target.value = '';
                      }
                    }}
                  />
                </label>
              )}
            </div>

            <div className="p-4">
              {selectedFiles.length === 0 ? (
                <p className="text-gray-500 text-center py-8">No images selected yet.</p>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                  {selectedFiles.map((file, i) => (
                    <div key={`${file.name}-${i}`} className="relative group border border-gray-200 rounded-lg overflow-hidden bg-gray-100">
                      <img
                        src={imageUrls[i]}
                        alt={`Product image ${i + 1}: ${file.name}`}
                        className="w-full h-40 object-contain"
                      />
                      <div className="p-2 bg-white">
                        <p className="text-xs font-medium text-gray-900">Image {i + 1}</p>
                        <p className="text-xs text-gray-500 truncate">{file.name}</p>
                      </div>
                      <button
                        onClick={() => handleRemoveFile(i)}
                        className="absolute top-2 right-2 w-7 h-7 rounded-full bg-black/60 text-white text-sm opacity-0 group-hover:opacity-100 hover:bg-red-600 transition flex items-center justify-center"
                        aria-label={`Remove image ${i + 1}`}
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-4 flex items-center justify-between gap-4">
                <p className="text-sm text-gray-500">
                  {selectedFiles.length > 1
                    ? 'Each side is OCRed separately; the verdict merges the strongest evidence.'
                    : 'Tip: add back/side photos — MRP is often on a different panel.'}
                </p>
                <button
                  onClick={handleAnalyze}
                  disabled={selectedFiles.length === 0}
                  className="px-6 py-2.5 bg-primary-600 text-white font-medium rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
                >
                  Analyze Product{selectedFiles.length > 1 ? ` (${selectedFiles.length} images)` : ''}
                </button>
              </div>
            </div>
          </div>
        </main>
      </div>
    );
  }

  if (stage === 'processing') {
    return (
      <div className="min-h-screen bg-gray-50">
        <header className="bg-white border-b border-gray-200">
          <div className="max-w-4xl mx-auto px-4 py-4">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-gray-900">CompliScan</h1>
              <span className="px-2 py-1 text-xs font-medium bg-primary-100 text-primary-700 rounded-full">Processing</span>
            </div>
          </div>
        </header>

        <main className="max-w-4xl mx-auto px-4 py-8">
          <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8 text-center">
            <svg className="mx-auto h-16 w-16 text-primary-500 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <h2 className="text-xl font-bold text-gray-900 mt-4">
              Analyzing Product{selectedFiles.length > 1 ? ` (${selectedFiles.length} images)` : ''}
            </h2>
            <p className="text-gray-500 mt-2">
              {selectedFiles.length > 1
                ? 'Scanning each side separately — this takes longer than a single photo…'
                : 'This may take a few seconds…'}
            </p>
          </div>

          <ProcessingSteps steps={processingSteps} />
        </main>
      </div>
    );
  }

  if (stage === 'results' && results) {
    const isMulti = results.kind === 'multi';
    const data = results.data;
    const { status, fields, checks, violations, review_items, quality } = data;
    const qualityWarning = quality && (quality.blurry || quality.tiny_text || quality.suspicious_layout);
    const images = isMulti ? (data as MultiAnalysisResponse).images : null;
    const single = isMulti ? null : (data as AnalysisResponse);
    const activeImage = images ? images[Math.min(selectedImgIdx, images.length - 1)] : null;
    const viewerAnnotated = activeImage ? activeImage.annotated_image || '' : single?.annotated_image || '';
    const viewerOriginal = activeImage ? activeImage.original_image || '' : single?.original_image || '';
    const viewerOcr = activeImage ? activeImage.ocr_results : single?.ocr_results ?? [];
    const viewerFields = activeImage ? activeImage.fields : fields;
    const totalRegions = images
      ? images.reduce((n, im) => n + im.ocr_regions, 0)
      : (single?.ocr_results.length ?? 0);

    return (
      <div className="min-h-screen bg-gray-50">
        <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
          <div className="max-w-7xl mx-auto px-4 py-4 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <button
                onClick={handleNewAnalysis}
                className="p-2 text-gray-500 hover:text-gray-700 rounded-lg hover:bg-gray-100 transition-colors"
                aria-label="New analysis"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </button>
              <div>
                <h1 className="text-xl font-bold text-gray-900">CompliScan</h1>
                <p className="text-sm text-gray-500">Packaged Commodity Compliance Scanner</p>
              </div>
            </div>
            <ComplianceStatusBadge status={status} size="lg" />
          </div>
        </header>

        <main className="max-w-7xl mx-auto px-4 py-6">
          {qualityWarning && (
            <div className="mb-6 p-4 bg-yellow-50 border border-yellow-300 rounded-xl text-yellow-800" role="alert">
              <p className="font-semibold">Photo quality is low — result needs human review.</p>
              <p className="text-sm mt-1">
                {quality?.blurry && `The image looks blurry (sharpness ${quality?.blur_score}). `}
                {quality?.tiny_text && `Declaration print looks very small (${quality?.median_text_height_px}px median text height). `}
                Please retake a sharp, straight-on, well-lit photo of the declaration panel and re-analyze.
              </p>
            </div>
          )}
          <p className="mb-4 text-sm text-gray-500">
            {isMulti ? `${images!.length} images` : '1 image'}
            {` • OCR found ${totalRegions} text regions`}
            {fields.length > 0 && ` • ${fields.length} declarations extracted`}
            {elapsedSecs !== null && ` • analyzed in ${elapsedSecs.toFixed(1)}s`}
          </p>

          {images && (
            <div className="mb-6 flex flex-wrap gap-2" role="tablist" aria-label="Product images">
              {images.map((im, i) => (
                <button
                  key={im.index}
                  role="tab"
                  aria-selected={i === selectedImgIdx}
                  onClick={() => setSelectedImgIdx(i)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
                    i === selectedImgIdx
                      ? 'bg-primary-600 text-white border-primary-600'
                      : 'bg-white text-gray-700 border-gray-300 hover:border-primary-400'
                  }`}
                >
                  Image {i + 1}
                  <span className={`ml-2 text-xs ${i === selectedImgIdx ? 'text-primary-100' : 'text-gray-400'}`}>
                    {im.ocr_regions} regions • {im.fields.length} fields
                  </span>
                  <span className={`block text-xs font-normal truncate max-w-[140px] ${i === selectedImgIdx ? 'text-primary-100' : 'text-gray-400'}`}>
                    {im.filename}
                  </span>
                </button>
              ))}
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left column - Image */}
            <div className="lg:col-span-1">
              <AnnotatedImageViewer
                annotatedImage={viewerAnnotated}
                originalImage={viewerOriginal}
                fields={viewerFields}
                checks={checks}
                ocrResults={viewerOcr}
              />
            </div>

            {/* Right column - Details */}
            <div className="lg:col-span-2 space-y-6">
              {/* Detected Information (merged across images) */}
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-1">Detected Information</h3>
                {isMulti && (
                  <p className="text-sm text-gray-500 mb-4">Merged across {images!.length} images — badge shows which image each declaration came from.</p>
                )}
                {fields.length > 0 ? (
                  <div className="space-y-3">
                    {fields.map((field) => {
                      const check = checks.find(c => c.field === field.name);
                      return (
                        <div key={field.name}>
                          {isMulti && field.source_image !== undefined && field.source_image !== null && (
                            <span className="inline-block mb-1 px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded-full">
                              Image {(field.source_image ?? 0) + 1}{field.source_filename ? ` • ${field.source_filename}` : ''}
                            </span>
                          )}
                          <FieldCard field={field} check={check} />
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-gray-500 text-center py-8">No declarations detected</p>
                )}
              </div>

              {/* Compliance Checks */}
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Compliance Checks</h3>
                <ChecksList checks={checks} />
              </div>

              {/* Violations */}
              <ViolationsList violations={violations} />

              {/* Review Items */}
              <ReviewItemsList reviewItems={review_items} />
            </div>
          </div>
        </main>
      </div>
    );
  }

  return null;
}

export default App;
