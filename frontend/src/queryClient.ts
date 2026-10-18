import { QueryClient } from '@tanstack/react-query'
export function createQueryClient(){return new QueryClient({defaultOptions:{queries:{retry:1,staleTime:5_000,refetchOnWindowFocus:false},mutations:{retry:false}}})}
