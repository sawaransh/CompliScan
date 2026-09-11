import React from 'react';
import type { ProcessingStep } from '../types';

interface ProcessingStepsProps {
  steps: ProcessingStep[];
}

const STEP_CONFIG: ProcessingStep[] = [
  { step: 1, name: 'Preparing image', description: 'Resizing and enhancing image quality', completed: false, active: false },
  { step: 2, name: 'Detecting text', description: 'Running PaddleOCR to find text regions', completed: false, active: false },
  { step: 3, name: 'Extracting declarations', description: 'Identifying MRP, quantity, manufacturer, dates', completed: false, active: false },
  { step: 4, name: 'Checking applicable rules', description: 'Validating against Legal Metrology requirements', completed: false, active: false },
  { step: 5, name: 'Preparing evidence', description: 'Creating annotated image with highlights', completed: false, active: false },
];

export const ProcessingSteps: React.FC<ProcessingStepsProps> = ({ steps }) => {
  const displaySteps = steps.length > 0 ? steps : STEP_CONFIG;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 animate-fade-in">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Processing Steps</h3>
      <div className="space-y-3">
        {displaySteps.map((step, index) => (
          <div
            key={step.step}
            className={`flex items-center gap-4 p-3 rounded-lg transition-colors ${
              step.completed ? 'bg-green-50' : step.active ? 'bg-primary-50' : 'bg-gray-50'
            }`}
          >
            <div
              className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                step.completed 
                  ? 'bg-green-500 text-white' 
                  : step.active 
                  ? 'bg-primary-500 text-white animate-pulse' 
                  : 'bg-gray-200 text-gray-500'
              }`}
            >
              {step.completed ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                </svg>
              ) : step.active ? (
                <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                step.step
              )}
            </div>
            <div className="flex-1 min-w-0">
              <p className={`font-medium truncate ${step.completed ? 'text-green-700' : step.active ? 'text-primary-700' : 'text-gray-700'}`}>
                {step.name}
              </p>
              <p className={`text-sm truncate ${step.completed ? 'text-green-600' : step.active ? 'text-primary-600' : 'text-gray-500'}`}>
                {step.description}
              </p>
            </div>
            {index < displaySteps.length - 1 && !step.completed && (
              <div className="hidden lg:block w-0.5 h-8 bg-gray-200 mx-2" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
};