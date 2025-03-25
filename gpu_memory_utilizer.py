#!/usr/bin/env python3
import torch
import time
import os
import psutil
import argparse

def get_free_memory(gpu_id):
    """Get free memory on GPU in bytes"""
    device = torch.device(f'cuda:{gpu_id}')
    stats = torch.cuda.memory_stats(device)
    free_memory = stats.get('reserved_bytes.all.current', 0) - stats.get('allocated_bytes.all.current', 0)
    return free_memory

def get_total_memory(gpu_id):
    """Get total memory on GPU in bytes"""
    return torch.cuda.get_device_properties(gpu_id).total_memory

def print_memory_usage(tensors_dict):
    """Print current memory usage for all GPUs"""
    process = psutil.Process(os.getpid())
    print(f"CPU Memory: {process.memory_info().rss / (1024 * 1024):.2f} MB")
    
    for gpu_id in range(torch.cuda.device_count()):
        total = get_total_memory(gpu_id) / (1024 * 1024)
        stats = torch.cuda.memory_stats(f'cuda:{gpu_id}')
        allocated = stats.get('allocated_bytes.all.current', 0) / (1024 * 1024)
        reserved = stats.get('reserved_bytes.all.current', 0) / (1024 * 1024)
        
        print(f"GPU {gpu_id}: {allocated:.2f} MB allocated / {reserved:.2f} MB reserved / {total:.2f} MB total "
              f"({100 * allocated / total:.1f}% used)")

def main():
    parser = argparse.ArgumentParser(description='Utilize a specified percentage of GPU memory')
    parser.add_argument('--percentage', type=float, default=50.0, 
                      help='Percentage of GPU memory to utilize (default: 50.0)')
    parser.add_argument('--sleep', type=float, default=10.0, 
                      help='Sleep time in seconds between memory checks (default: 10.0)')
    args = parser.parse_args()
    
    target_percentage = args.percentage / 100.0
    sleep_time = args.sleep
    
    print(f"Target: Utilizing approximately {args.percentage}% of each GPU's memory")
    print(f"Available GPUs: {torch.cuda.device_count()}")
    
    # Dictionary to store tensors for each GPU
    tensors_dict = {}
    
    try:
        for gpu_id in range(torch.cuda.device_count()):
            # Allocate tensors on the GPU to use target_percentage of memory
            device = torch.device(f'cuda:{gpu_id}')
            total_memory = get_total_memory(gpu_id)
            target_memory = int(total_memory * target_percentage)
            
            # Start with a small tensor
            tensors_dict[gpu_id] = torch.ones((1, 1), device=device)
            
            # Gradually increase tensor size to reach target
            while get_free_memory(gpu_id) > (total_memory - target_memory):
                current_memory = torch.cuda.memory_allocated(device)
                # Try to allocate more memory, about 256MB at a time
                size = 64 * 1024 * 1024  # 64 MB chunks
                try:
                    tensors_dict[gpu_id] = torch.cat([
                        tensors_dict[gpu_id],
                        torch.ones((size,), device=device)
                    ])
                except RuntimeError as e:
                    # If we get an out of memory error, try a smaller allocation
                    if "out of memory" in str(e):
                        size = size // 2
                        if size < 1024:  # If we're down to very small chunks, we're close enough
                            break
                    else:
                        raise e
                
                # Print current memory stats
                print_memory_usage(tensors_dict)
        
        print("\nMemory allocation complete. Maintaining allocation in a loop...")
        
        # Main loop to maintain the memory allocation
        while True:
            print("\n" + "="*80)
            print(f"Memory usage at {time.strftime('%Y-%m-%d %H:%M:%S')}:")
            print_memory_usage(tensors_dict)
            
            # Do a small computation to ensure the GPU is active
            for gpu_id in range(torch.cuda.device_count()):
                if gpu_id in tensors_dict:
                    device = torch.device(f'cuda:{gpu_id}')
                    # Just a small computation to keep things active
                    dummy = torch.ones((1000, 1000), device=device)
                    dummy = dummy + dummy
                    del dummy
                    torch.cuda.empty_cache()
            
            time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        print("\nExiting gracefully...")
    finally:
        # Clean up
        for gpu_id in tensors_dict:
            del tensors_dict[gpu_id]
        torch.cuda.empty_cache()
        print("Memory released")

if __name__ == "__main__":
    main() 