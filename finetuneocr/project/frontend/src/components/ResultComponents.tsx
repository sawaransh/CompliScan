import React from 'react';
import type { ComplianceStatus, ExtractedField, ComplianceCheck, Violation, ReviewItem } from '../types';

interface ComplianceStatusBadgeProps {
  status: ComplianceStatus;
  size?: 'sm' | 'md' | 'lg';
}

export const ComplianceStatusBadge: React.FC<ComplianceStatusBadgeProps> = ({ 
  status, 
  size = 'md' 
}) => {
  const configs = {
    COMPLIANT: {
      label: 'COMPLIANT',
      icon: '✓',
      bg: 'bg-green-100',
      text: 'text-green-800',
      border: 'border-green-300',
      iconBg: 'bg-green-500',
    },
    NON_COMPLIANT: {
      label: 'NON-COMPLIANT',
      icon: '✗',
      bg: 'bg-red-100',
      text: 'text-red-800',
      border: 'border-red-300',
      iconBg: 'bg-red-500',
    },
    REVIEW_REQUIRED: {
      label: 'REVIEW REQUIRED',
      icon: '⚠',
      bg: 'bg-yellow-100',
      text: 'text-yellow-800',
      border: 'border-yellow-300',
      iconBg: 'bg-yellow-500',
    },
  };

  const config = configs[status];
  const sizeClasses = {
    sm: 'px-2 py-1 text-xs gap-1',
    md: 'px-4 py-2 text-sm gap-2',
    lg: 'px-6 py-3 text-base gap-3',
  };

  return (
    <div
      className={`inline-flex items-center ${config.bg} ${config.text} ${config.border} border rounded-full font-semibold ${sizeClasses[size]}`}
      role="status"
      aria-label={`Compliance status: ${config.label}`}
    >
      <span className={`${config.iconBg} text-white rounded-full w-5 h-5 flex items-center justify-center text-xs font-bold`}>
        {config.icon}
      </span>
      <span>{config.label}</span>
    </div>
  );
};

interface ConfidenceBarProps {
  confidence: number;
  showValue?: boolean;
}

export const ConfidenceBar: React.FC<ConfidenceBarProps> = ({ confidence, showValue = true }) => {
  const percentage = Math.round(confidence * 100);
  const color = confidence >= 0.8 ? 'bg-green-500' : confidence >= 0.6 ? 'bg-yellow-500' : 'bg-red-500';

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`${color} h-full rounded-full transition-all duration-300`}
          style={{ width: `${percentage}%` }}
          role="progressbar"
          aria-valuenow={percentage}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Confidence: ${percentage}%`}
        />
      </div>
      {showValue && (
        <span className="text-xs font-medium text-gray-600 w-10 text-right">
          {percentage}%
        </span>
      )}
    </div>
  );
};

interface FieldCardProps {
  field: ExtractedField;
  check?: ComplianceCheck;
}

export const FieldCard: React.FC<FieldCardProps> = ({ field, check }) => {
  const getStatusColor = (status?: string) => {
    switch (status) {
      case 'PASS': return 'text-green-600 bg-green-50 border-green-200';
      case 'FAIL': return 'text-red-600 bg-red-50 border-red-200';
      case 'REVIEW': return 'text-yellow-600 bg-yellow-50 border-yellow-200';
      default: return 'text-gray-600 bg-gray-50 border-gray-200';
    }
  };

  const status = check?.status;
  const statusLabel = status ? (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${getStatusColor(status)}`}>
      {status}
    </span>
  ) : null;

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <span className="font-medium text-gray-900 capitalize">{field.name.replace('_', ' ')}</span>
            {statusLabel}
          </div>
          <p className="text-gray-700 font-mono text-sm break-all">{field.value}</p>
          <div className="mt-2">
            <ConfidenceBar confidence={field.confidence} />
          </div>
        </div>
      </div>
      {check?.message && (
        <p className="mt-2 text-xs text-gray-500">{check.message}</p>
      )}
    </div>
  );
};

interface ChecksListProps {
  checks: ComplianceCheck[];
}

export const ChecksList: React.FC<ChecksListProps> = ({ checks }) => {
  const getIcon = (status: string) => {
    switch (status) {
      case 'PASS':
        return (
          <svg className="w-5 h-5 text-green-500" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
          </svg>
        );
      case 'FAIL':
        return (
          <svg className="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
        );
      case 'REVIEW':
        return (
          <svg className="w-5 h-5 text-yellow-500" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
          </svg>
        );
      default:
        return (
          <svg className="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
            <path d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" />
          </svg>
        );
    }
  };

  return (
    <div className="space-y-2">
      {checks.map((check) => (
        <div
          key={check.rule_id}
          className="flex items-center gap-3 p-3 bg-white border border-gray-200 rounded-lg"
        >
          <div className="flex-shrink-0">{getIcon(check.status)}</div>
          <div className="flex-1 min-w-0">
            <p className="font-medium text-gray-900 capitalize">{check.field.replace('_', ' ')}</p>
            <p className="text-sm text-gray-500">{check.message}</p>
          </div>
          <span className="text-xs font-medium px-2 py-1 rounded-full bg-gray-100 text-gray-600">
            {check.rule_id}
          </span>
        </div>
      ))}
    </div>
  );
};

interface ViolationsListProps {
  violations: Violation[];
}

export const ViolationsList: React.FC<ViolationsListProps> = ({ violations }) => {
  if (violations.length === 0) return null;

  return (
    <div className="space-y-3">
      <h4 className="font-semibold text-red-700 flex items-center gap-2">
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
        </svg>
        Violations ({violations.length})
      </h4>
      {violations.map((violation, index) => (
        <div key={index} className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
            </svg>
            <div className="flex-1">
              <p className="font-medium text-red-800">{violation.requirement}</p>
              <p className="text-sm text-red-700 mt-1">{violation.reason}</p>
              <p className="text-xs text-red-600 mt-1 font-mono">{violation.rule_id}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};

interface ReviewItemsListProps {
  reviewItems: ReviewItem[];
}

export const ReviewItemsList: React.FC<ReviewItemsListProps> = ({ reviewItems }) => {
  if (reviewItems.length === 0) return null;

  return (
    <div className="space-y-3">
      <h4 className="font-semibold text-yellow-700 flex items-center gap-2">
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
        </svg>
        Review Required ({reviewItems.length})
      </h4>
      {reviewItems.map((item, index) => (
        <div key={index} className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-yellow-500 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            <div className="flex-1">
              <p className="font-medium text-yellow-800">{item.requirement}</p>
              <p className="text-sm text-yellow-700 mt-1">{item.reason}</p>
              <div className="flex items-center gap-2 mt-2">
                <span className="text-xs text-yellow-600 font-mono">{item.rule_id}</span>
                <ConfidenceBar confidence={item.confidence} showValue />
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
};