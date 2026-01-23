import React from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { BackButton } from '@/components/ui/BackButton';

interface HeaderProps {
    title?: string;
    onBack?: () => void;
    showBack?: boolean;
    rightElement?: React.ReactNode;
    className?: string;
}

export const Header: React.FC<HeaderProps> = ({
    title,
    onBack,
    showBack = true,
    rightElement,
    className
}) => {
    const navigate = useNavigate();

    const handleBack = () => {
        if (onBack) {
            onBack();
        } else {
            navigate(-1);
        }
    };

    return (
        <header className={cn("flex items-center justify-between p-6 z-10 relative", className)}>
            <div className="w-10">
                {showBack && (
                    <BackButton onClick={handleBack} />
                )}
            </div>

            <h1 className="text-xl font-bold text-neu-text tracking-wide text-center flex-1">
                {title}
            </h1>

            <div className="w-10 flex justify-end">
                {rightElement}
            </div>
        </header>
    );
};
