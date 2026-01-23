import React, { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/utils';
import { AnimatePresence, motion } from 'framer-motion';

// --- Types ---
type ToastType = 'success' | 'error' | 'info' | 'warning';

interface ToastMessage {
    id: string;
    message: string;
    type: ToastType;
}

interface ToastContextType {
    showToast: (message: string, type?: ToastType) => void;
}

// --- Context ---
const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const useToast = () => {
    const context = useContext(ToastContext);
    if (!context) {
        throw new Error('useToast must be used within a ToastProvider');
    }
    return context;
};

// --- Component ---
export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [toasts, setToasts] = useState<ToastMessage[]>([]);
    const timersRef = useRef<Set<NodeJS.Timeout>>(new Set());

    useEffect(() => {
        return () => {
            // Cleanup all timers on unmount
            if (timersRef.current) {
                timersRef.current.forEach(timer => clearTimeout(timer));
                timersRef.current.clear();
            }
        };
    }, []);

    const showToast = useCallback((message: string, type: ToastType = 'info') => {
        const id = Date.now().toString();
        setToasts((prev) => [...prev, { id, message, type }]);

        // Auto remove after 3 seconds
        const timer = setTimeout(() => {
            setToasts((prev) => prev.filter((t) => t.id !== id));
            timersRef.current.delete(timer);
        }, 3000);

        timersRef.current.add(timer);
    }, []);

    return (
        <ToastContext.Provider value={{ showToast }}>
            {children}
            {createPortal(
                <div className="fixed top-6 left-1/2 -translate-x-1/2 z-[100] flex flex-col gap-2 pointer-events-none">
                    <AnimatePresence>
                        {toasts.map((toast) => (
                            <motion.div
                                key={toast.id}
                                initial={{ opacity: 0, y: -20, scale: 0.9 }}
                                animate={{ opacity: 1, y: 0, scale: 1 }}
                                exit={{ opacity: 0, y: -20, scale: 0.9 }}
                                transition={{ duration: 0.3 }}
                                className={cn(
                                    "pointer-events-auto flex items-center gap-3 px-6 py-3 rounded-full shadow-neu-flat backdrop-blur-md min-w-[200px] justify-center",
                                    toast.type === 'success' ? "bg-green-50 text-green-700 border border-green-200" :
                                        toast.type === 'error' ? "bg-red-50 text-red-700 border border-red-200" :
                                            "bg-neu-bg/90 text-neu-text border border-white/40"
                                )}
                            >
                                {toast.type === 'success' && <span className="material-symbols-outlined text-sm">check_circle</span>}
                                {toast.type === 'error' && <span className="material-symbols-outlined text-sm">error</span>}
                                {toast.type === 'info' && <span className="material-symbols-outlined text-sm">info</span>}
                                <span className="text-sm font-bold tracking-wide">{toast.message}</span>
                            </motion.div>
                        ))}
                    </AnimatePresence>
                </div>,
                document.body
            )}
        </ToastContext.Provider>
    );
};
