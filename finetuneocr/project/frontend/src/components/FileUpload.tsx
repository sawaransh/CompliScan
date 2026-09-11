import React, { useState, useRef } from 'react';

interface FileUploadProps {
  onFileSelect: (file: File) => void;
  onFilesSelect?: (files: File[]) => void;
  multiple?: boolean;
  disabled?: boolean;
}

export const FileUpload: React.FC<FileUploadProps> = ({ onFileSelect, onFilesSelect, multiple, disabled }) => {
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const MAX_BYTES = 10 * 1024 * 1024;

  const validateFile = (file: File): string | null => {
    const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/heic', 'image/heif'];
    const validExt = /\.(jpe?g|png|webp|heic|heif)$/i.test(file.name);
    if (!validTypes.includes(file.type) && !validExt) {
      return 'Please select a valid image file (JPG, JPEG, PNG, WEBP, HEIC)';
    }
    if (file.size > MAX_BYTES) {
      return `Image is ${(file.size / 1024 / 1024).toFixed(1)}MB — please use a file under 10MB`;
    }
    if (file.size === 0) {
      return 'That file looks empty — please choose another image';
    }
    return null;
  };

  const submitFiles = (list: FileList | File[]) => {
    const files = Array.from(list);
    if (files.length === 0) return;
    if (multiple && onFilesSelect) {
      const bad = files.map(validateFile).find((e) => e !== null);
      if (bad) {
        alert(bad);
        return;
      }
      onFilesSelect(files);
      return;
    }
    const file = files[0];
    const err = validateFile(file);
    if (!err) {
      onFileSelect(file);
    } else {
      alert(err);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      submitFiles(e.dataTransfer.files);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      submitFiles(e.target.files);
      e.target.value = '';
    }
  };

  const openFileDialog = () => {
    fileInputRef.current?.click();
  };

  return (
    <div
      className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
        dragActive 
          ? 'border-primary-500 bg-primary-50' 
          : 'border-gray-300 hover:border-primary-400'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
      onDragEnter={handleDrag}
      onDragLeave={handleDrag}
      onDragOver={handleDrag}
      onDrop={handleDrop}
      onClick={!disabled ? openFileDialog : undefined}
      role="button"
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(e) => !disabled && (e.key === 'Enter' || e.key === ' ') && openFileDialog()}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/jpg,image/png,image/webp,image/heic,image/heif,.heic,.heif"
        multiple={multiple}
        onChange={handleFileChange}
        className="hidden"
        disabled={disabled}
        aria-label="Upload product image"
      />
      
      <div className="space-y-4">
        <svg
          className="mx-auto h-12 w-12 text-gray-400"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
          />
        </svg>
        
        <div className="space-y-2">
          <p className="text-lg font-medium text-gray-900">
            {multiple ? 'Upload Product Images' : 'Upload Product Image'}
          </p>
          <p className="text-gray-500">
            {multiple
              ? 'Front, back & sides of ONE product — verdict merges all images'
              : 'Drag and drop or click to browse'}
          </p>
          <p className="text-sm text-gray-400">
            JPG, JPEG, PNG, WEBP, HEIC • Max 10MB
          </p>
          <p className="text-xs text-gray-400">
            Tip: sharp, straight-on, well-lit photo of the declaration panel
          </p>
        </div>
      </div>
    </div>
  );
};