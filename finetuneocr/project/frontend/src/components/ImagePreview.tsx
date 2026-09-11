import React from 'react';

interface ImagePreviewProps {
  imageUrl: string;
  fileName: string;
  onAnalyze: () => void;
  analyzing?: boolean;
}

export const ImagePreview: React.FC<ImagePreviewProps> = ({
  imageUrl,
  fileName,
  onAnalyze,
  analyzing,
}) => {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden animate-fade-in">
      <div className="p-4 border-b border-gray-200">
        <h3 className="text-lg font-semibold text-gray-900">Product Preview</h3>
      </div>
      
      <div className="p-4">
        <div className="relative aspect-video bg-gray-100 rounded-lg overflow-hidden">
          <img
            src={imageUrl}
            alt={`Product image: ${fileName}`}
            className="w-full h-full object-contain"
          />
        </div>
        
        <div className="mt-4 flex items-center justify-between">
          <p className="text-sm text-gray-600 truncate max-w-xs">{fileName}</p>
          <button
            onClick={onAnalyze}
            disabled={analyzing}
            className="px-6 py-2.5 bg-primary-600 text-white font-medium rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
          >
            {analyzing ? (
              <>
                <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                    fill="none"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Analyzing...
              </>
            ) : (
              'Analyze Product'
            )}
          </button>
        </div>
      </div>
    </div>
  );
};