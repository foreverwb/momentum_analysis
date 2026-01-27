import { useState, useCallback } from 'react';

interface UseModalReturn<T = undefined> {
  isOpen: boolean;
  data: T | undefined;
  open: (data?: T) => void;
  close: () => void;
  toggle: () => void;
}

export function useModal<T = undefined>(initialState = false): UseModalReturn<T> {
  const [isOpen, setIsOpen] = useState(initialState);
  const [data, setData] = useState<T | undefined>(undefined);

  const open = useCallback((modalData?: T) => {
    setData(modalData);
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
    // Clear data after animation completes
    setTimeout(() => setData(undefined), 200);
  }, []);

  const toggle = useCallback(() => {
    setIsOpen((prev) => !prev);
  }, []);

  return { isOpen, data, open, close, toggle };
}

// Multi-modal manager for managing multiple modals
interface ModalState {
  [key: string]: {
    isOpen: boolean;
    data?: unknown;
  };
}

interface UseModalsReturn {
  modals: ModalState;
  openModal: (name: string, data?: unknown) => void;
  closeModal: (name: string) => void;
  isModalOpen: (name: string) => boolean;
  getModalData: <T>(name: string) => T | undefined;
}

export function useModals(modalNames: string[]): UseModalsReturn {
  const initialState = modalNames.reduce((acc, name) => {
    acc[name] = { isOpen: false, data: undefined };
    return acc;
  }, {} as ModalState);

  const [modals, setModals] = useState<ModalState>(initialState);

  const openModal = useCallback((name: string, data?: unknown) => {
    setModals((prev) => ({
      ...prev,
      [name]: { isOpen: true, data },
    }));
  }, []);

  const closeModal = useCallback((name: string) => {
    setModals((prev) => ({
      ...prev,
      [name]: { ...prev[name], isOpen: false },
    }));
  }, []);

  const isModalOpen = useCallback(
    (name: string) => modals[name]?.isOpen ?? false,
    [modals]
  );

  const getModalData = useCallback(
    <T>(name: string): T | undefined => modals[name]?.data as T | undefined,
    [modals]
  );

  return { modals, openModal, closeModal, isModalOpen, getModalData };
}
