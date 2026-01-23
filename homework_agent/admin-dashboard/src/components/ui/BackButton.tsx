import React from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@/lib/utils';

type BackButtonProps = {
  to?: string;
  onClick?: () => void;
  className?: string;
  iconClassName?: string;
  ariaLabel?: string;
};

export const BackButton: React.FC<BackButtonProps> = ({
  to,
  onClick,
  className,
  iconClassName,
  ariaLabel = 'Go back',
}) => {
  const navigate = useNavigate();

  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={() => {
        if (onClick) return onClick();
        if (to) return navigate(to);
        return navigate(-1);
      }}
      className={cn(
        'w-10 h-10 rounded-full bg-neu-bg shadow-neu-icon-btn flex items-center justify-center',
        'text-neu-text-secondary hover:text-neu-text active:text-primary active:shadow-neu-pressed transition-all duration-300',
        className
      )}
    >
      <span
        aria-hidden
        className={cn(
          'material-symbols-outlined text-[24px] select-none',
          iconClassName
        )}
        style={{
          fontVariationSettings: "'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24",
        }}
      >
        chevron_left
      </span>
    </button>
  );
};
