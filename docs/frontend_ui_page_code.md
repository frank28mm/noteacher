# 主页
这是主页的UI代码
<!DOCTYPE html>
<html class="light" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Noteacher Home - Flow State</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script id="tailwind-config">
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        "primary": "#3B82F6", // Tech blue
                        "accent": "#FCD34D", // Bright yellow
                        "neu-bg": "#EFEEEE", // Updated to standard grey white
                        "neu-text": "#1F2937", // Deep black/gray
                        "neu-text-secondary": "#9CA3AF", // Mid gray
                    },
                    fontFamily: {
                        "display": ["Lexend", "Noto Sans", "sans-serif"]
                    },
                    boxShadow: {
                        // Adjusted shadows for #EFEEEE background
                        'neu-base': '12px 12px 24px #cccccc, -12px -12px 24px #ffffff',
                        'neu-inset': 'inset 6px 6px 12px #cccccc, inset -6px -6px 12px #ffffff',
                        'neu-inset-sm': 'inset 3px 3px 6px #cccccc, inset -3px -3px 6px #ffffff',
                        'neu-plate': '20px 20px 60px #cccccc, -20px -20px 60px #ffffff',
                        'neu-circle': '8px 8px 16px #cccccc, -8px -8px 16px #ffffff',
                        'neu-circle-pressed': 'inset 4px 4px 8px #cccccc, inset -4px -4px 8px #ffffff',
                        'neu-nav': '0 -10px 30px rgba(255,255,255,0.8), 0 10px 30px rgba(0,0,0,0.05)',
                        'flow-ring': '10px 10px 20px #cccccc, -10px -10px 20px #ffffff, inset 10px 10px 20px rgba(204, 204, 204, 0.2), inset -10px -10px 20px rgba(255, 255, 255, 0.8)',
                    }
                },
            },
        }
    </script>
<style>
        .material-symbols-outlined {
            font-variation-settings: 'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24;
        }
        body {
             background-color: #EFEEEE;
             min-height: 100vh;
             font-family: 'Lexend', sans-serif;
        }
        .no-scrollbar::-webkit-scrollbar {
            display: none;
        }
        .no-scrollbar {
            -ms-overflow-style: none;
            scrollbar-width: none;
        }
        .neu-ring-container {
            position: relative;
            border-radius: 50%;
            background: #EFEEEE;
            box-shadow: 10px 10px 20px #cccccc, -10px -10px 20px #ffffff;
        }
        .neu-ring-inner {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            border-radius: 50%;
            background: #EFEEEE;
            box-shadow: inset 5px 5px 10px #cccccc, inset -5px -5px 10px #ffffff;
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-neu-bg text-neu-text transition-colors duration-200 antialiased overflow-hidden">
<div class="relative flex h-full min-h-screen w-full flex-col max-w-md mx-auto bg-neu-bg pb-12">
<header class="flex items-center px-8 pt-10 pb-4 justify-between z-20">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-neu-text-secondary" style="font-size: 20px;">edit</span>
<h2 class="text-sm font-bold tracking-widest text-neu-text-secondary uppercase">No Teacher</h2>
</div>
<button class="relative h-10 w-10 rounded-full flex items-center justify-center shadow-neu-circle active:shadow-neu-circle-pressed transition-all duration-300 bg-neu-bg">
<div class="h-8 w-8 rounded-full overflow-hidden">
<img alt="User avatar" class="h-full w-full object-cover opacity-90" src="https://lh3.googleusercontent.com/aida-public/AB6AXuDg1fxYspybNS96gWgLQtkYOZD3tCBUtr2EUMKzFOs8O7itQlBfAqfAr4UPNLXq7Wqwfbca-HvC0FQOzjqul-ffcbW-PQsRa8092IS2L2DuGBr6SNGaJywhUDAseqEIEFuHjlf9GJI2Z5Gtej3Xibg7eiH79dXoY1ONRu7DdQOywVfiFSNc7silMO0abmGC7LnWR0Vp2cxwWnacuh4Aca0s6d3Ml7xwF8kQxHjyZFR5oAx9TFuVRbYBKNxCk2DLGlE5QhHlGf_cjHg"/>
</div>
<div class="absolute top-0 right-0 h-2.5 w-2.5 rounded-full bg-green-500 border-2 border-neu-bg shadow-sm"></div>
</button>
</header>
<main class="flex-1 flex flex-col items-center justify-center relative px-6 -mt-10">
<div class="relative w-80 h-80 rounded-full flex items-center justify-center mb-12">
<div class="absolute inset-0 rounded-full bg-neu-bg shadow-flow-ring flex items-center justify-center">
<div class="w-64 h-64 rounded-full bg-neu-bg shadow-neu-inset flex flex-col items-center justify-center relative overflow-hidden">
<div class="absolute top-0 w-full h-full bg-gradient-to-tr from-transparent via-white/20 to-transparent pointer-events-none rounded-full"></div>
<button class="group flex flex-col items-center justify-center z-10 w-full h-full rounded-full focus:outline-none active:scale-95 transition-transform duration-200">
<span class="material-symbols-outlined text-neu-text !text-[64px] mb-2 group-hover:text-primary transition-colors duration-300" style="font-variation-settings: 'FILL' 1, 'wght' 300;">photo_camera</span>
<span class="text-xs font-bold tracking-widest text-neu-text-secondary uppercase mt-2 group-hover:text-primary transition-colors duration-300">Tap to Scan</span>
</button>
</div>
</div>
<div class="absolute inset-[8px] rounded-full border border-white/40 shadow-sm pointer-events-none"></div>
</div>
<div class="grid grid-cols-2 gap-x-12 gap-y-10">
<div class="flex flex-col items-center gap-3">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-circle flex items-center justify-center text-neu-text-secondary hover:text-neu-text active:shadow-neu-circle-pressed active:text-primary active:scale-95 transition-all duration-200 group">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform">history</span>
</button>
<span class="text-[10px] font-bold tracking-widest text-red-500 uppercase">HISTORY</span>
</div>
<div class="flex flex-col items-center gap-3">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-circle flex items-center justify-center text-neu-text-secondary hover:text-neu-text active:shadow-neu-circle-pressed active:text-primary active:scale-95 transition-all duration-200 group">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform">database</span>
</button>
<span class="text-[10px] font-bold tracking-widest text-red-500 uppercase">DATA</span>
</div>
<div class="flex flex-col items-center gap-3">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-circle flex items-center justify-center text-neu-text-secondary hover:text-neu-text active:shadow-neu-circle-pressed active:text-primary active:scale-95 transition-all duration-200 group">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform">bar_chart</span>
</button>
<span class="text-[10px] font-bold tracking-widest text-red-500 uppercase">ANALYSIS</span>
</div>
<div class="flex flex-col items-center gap-3">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-circle flex items-center justify-center text-neu-text-secondary hover:text-neu-text active:shadow-neu-circle-pressed active:text-primary active:scale-95 transition-all duration-200 group">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform">person</span>
</button>
<span class="text-[10px] font-bold tracking-widest text-red-500 uppercase">Mine</span>
</div>
</div>
</main>
</div>
</body></html>

## 主页-任务进行中/任务完成(用户未查看) 
<!DOCTYPE html>
<html class="light" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Noteacher Home - Flow State</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script id="tailwind-config">
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        "primary": "#3B82F6", // Tech blue
                        "accent": "#FCD34D", // Bright yellow
                        "neu-bg": "#EFEEEE", // Unified warm gray-white background
                        "neu-text": "#1F2937", // Deep black/gray
                        "neu-text-secondary": "#9CA3AF", // Mid gray
                    },
                    fontFamily: {
                        "display": ["Lexend", "Noto Sans", "sans-serif"]
                    },
                    boxShadow: {
                        // Shadows adjusted to be neutral/warm gray (#d1d1d1) to match #EFEEEE background
                        'neu-base': '12px 12px 24px #d1d1d1, -12px -12px 24px #ffffff',
                        'neu-inset': 'inset 6px 6px 12px #d1d1d1, inset -6px -6px 12px #ffffff',
                        'neu-inset-sm': 'inset 3px 3px 6px #d1d1d1, inset -3px -3px 6px #ffffff',
                        'neu-plate': '20px 20px 60px #d1d1d1, -20px -20px 60px #ffffff',
                        'neu-circle': '8px 8px 16px #d1d1d1, -8px -8px 16px #ffffff',
                        'neu-circle-pressed': 'inset 4px 4px 8px #d1d1d1, inset -4px -4px 8px #ffffff',
                        'neu-nav': '0 -10px 30px rgba(255,255,255,0.8), 0 10px 30px rgba(0,0,0,0.05)',
                        'flow-ring': '10px 10px 20px #d1d1d1, -10px -10px 20px #ffffff, inset 10px 10px 20px rgba(209, 209, 209, 0.2), inset -10px -10px 20px rgba(255, 255, 255, 0.8)',
                    }
                },
            },
        }
    </script>
<style>
        .material-symbols-outlined {
            font-variation-settings: 'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24;
        }
        body {
             background-color: #EFEEEE;
             min-height: 100vh;
             font-family: 'Lexend', sans-serif;
        }
        .no-scrollbar::-webkit-scrollbar {
            display: none;
        }
        .no-scrollbar {
            -ms-overflow-style: none;
            scrollbar-width: none;
        }
        .neu-ring-container {
            position: relative;
            border-radius: 50%;
            background: #EFEEEE;
            box-shadow: 10px 10px 20px #d1d1d1, -10px -10px 20px #ffffff;
        }
        .neu-ring-inner {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            border-radius: 50%;
            background: #EFEEEE;
            box-shadow: inset 5px 5px 10px #d1d1d1, inset -5px -5px 10px #ffffff;
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-neu-bg text-neu-text transition-colors duration-200 antialiased overflow-hidden">
<div class="relative flex h-full min-h-screen w-full flex-col max-w-md mx-auto bg-neu-bg pb-12">
<header class="flex items-center px-8 pt-10 pb-4 justify-between z-20">
<div class="flex items-center gap-2">
<span class="material-symbols-outlined text-neu-text-secondary" style="font-size: 20px;">edit</span>
<h2 class="text-sm font-bold tracking-widest text-neu-text-secondary uppercase">No Teacher</h2>
</div>
<button class="relative h-10 w-10 rounded-full flex items-center justify-center shadow-neu-circle active:shadow-neu-circle-pressed transition-all duration-300 bg-neu-bg">
<div class="h-8 w-8 rounded-full overflow-hidden">
<img alt="User avatar" class="h-full w-full object-cover opacity-90" src="https://lh3.googleusercontent.com/aida-public/AB6AXuDg1fxYspybNS96gWgLQtkYOZD3tCBUtr2EUMKzFOs8O7itQlBfAqfAr4UPNLXq7Wqwfbca-HvC0FQOzjqul-ffcbW-PQsRa8092IS2L2DuGBr6SNGaJywhUDAseqEIEFuHjlf9GJI2Z5Gtej3Xibg7eiH79dXoY1ONRu7DdQOywVfiFSNc7silMO0abmGC7LnWR0Vp2cxwWnacuh4Aca0s6d3Ml7xwF8kQxHjyZFR5oAx9TFuVRbYBKNxCk2DLGlE5QhHlGf_cjHg"/>
</div>
<div class="absolute top-0 right-0 h-2.5 w-2.5 rounded-full bg-green-500 border-2 border-neu-bg shadow-sm"></div>
</button>
</header>
<main class="flex-1 flex flex-col items-center justify-center relative px-6 -mt-10">
<div class="relative w-80 h-80 rounded-full flex items-center justify-center mb-12">
<div class="absolute inset-0 rounded-full bg-neu-bg shadow-flow-ring flex items-center justify-center">
<div class="w-64 h-64 rounded-full bg-neu-bg shadow-neu-inset flex flex-col items-center justify-center relative overflow-hidden">
<div class="absolute top-0 w-full h-full bg-gradient-to-tr from-transparent via-white/20 to-transparent pointer-events-none rounded-full"></div>
<button class="group flex flex-col items-center justify-center z-10 w-full h-full rounded-full focus:outline-none active:scale-95 transition-transform duration-200">
<span class="material-symbols-outlined text-neu-text !text-[64px] mb-2 group-hover:text-primary transition-colors duration-300" style="font-variation-settings: 'FILL' 1, 'wght' 300;">photo_camera</span>
<span class="text-xs font-bold tracking-widest text-neu-text-secondary uppercase mt-2 group-hover:text-primary transition-colors duration-300">Tap to Scan</span>
</button>
</div>
</div>
<div class="absolute inset-[8px] rounded-full border border-white/40 shadow-sm pointer-events-none"></div>
</div>
<div class="grid grid-cols-2 gap-x-12 gap-y-10">
<div class="flex flex-col items-center gap-3">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-circle flex items-center justify-center text-neu-text-secondary hover:text-neu-text active:shadow-neu-circle-pressed active:text-primary active:scale-95 transition-all duration-200 group">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform">history</span>
</button>
<span class="text-[10px] font-bold tracking-widest text-red-500 uppercase">History</span>
</div>
<div class="flex flex-col items-center gap-3">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-circle flex items-center justify-center text-neu-text-secondary hover:text-neu-text active:shadow-neu-circle-pressed active:text-primary active:scale-95 transition-all duration-200 group">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform">database</span>
</button>
<span class="text-[10px] font-bold tracking-widest text-red-500 uppercase">DATA</span>
</div>
<div class="flex flex-col items-center gap-3">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-circle flex items-center justify-center text-neu-text-secondary hover:text-neu-text active:shadow-neu-circle-pressed active:text-primary active:scale-95 transition-all duration-200 group">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform">bar_chart</span>
</button>
<span class="text-[10px] font-bold tracking-widest text-red-500 uppercase">ANALYSIS</span>
</div>
<div class="flex flex-col items-center gap-3">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-circle flex items-center justify-center text-neu-text-secondary hover:text-neu-text active:shadow-neu-circle-pressed active:text-primary active:scale-95 transition-all duration-200 group">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform">person</span>
</button>
<span class="text-[10px] font-bold tracking-widest text-red-500 uppercase">Mine</span>
</div>
</div>
</main>
<div class="absolute bottom-8 left-6 right-6 z-30">
<div class="bg-neu-bg rounded-2xl shadow-neu-base p-4 flex items-center gap-4 border border-white/50">
<div class="h-10 w-10 flex-shrink-0 rounded-full bg-neu-bg shadow-neu-circle flex items-center justify-center text-primary">
<span class="material-symbols-outlined animate-spin" style="font-size: 20px;">sync</span>
</div>
<div class="flex-1 min-w-0">
<div class="flex items-center justify-between mb-2">
<span class="text-xs font-bold tracking-wider text-neu-text uppercase">Processing</span>
<span class="text-[10px] font-semibold text-neu-text-secondary">75%</span>
</div>
<div class="h-1.5 w-full rounded-full bg-neu-bg shadow-neu-inset-sm overflow-hidden">
<div class="h-full w-3/4 rounded-full bg-primary shadow-[2px_2px_4px_rgba(0,0,0,0.1)]"></div>
</div>
</div>
</div>
</div>
</div>
</body></html>

# 智能批改
## 拍照页面
<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" name="viewport"/>
<title>首页 (拍照界面 - 统一配色)</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        // Standard Gray-White Base
                        bg: '#EFEEEE', 
                        'shadow-light': '#ffffff',
                        'shadow-dark': '#d1d1d1', 
                        'text-main': '#475569', 
                        'primary': '#6366f1', 
                        'primary-shine': '#818cf8',
                    },
                    fontFamily: {
                        "display": ["Lexend", "Noto Sans", "sans-serif"]
                    },
                    boxShadow: {
                        // Updated shadows for #EFEEEE background (Neutral Grays)
                        'flow-flat': '12px 12px 24px #d1d1d1, -12px -12px 24px #ffffff',
                        'flow-flat-sm': '6px 6px 12px #d1d1d1, -6px -6px 12px #ffffff',
                        'flow-pressed': 'inset 8px 8px 16px #d1d1d1, inset -8px -8px 16px #ffffff',
                        'flow-pressed-sm': 'inset 4px 4px 8px #d1d1d1, inset -4px -4px 8px #ffffff',
                        // High-def clean button shadow
                        'flow-btn': '10px 10px 20px #cacad1, -10px -10px 20px #ffffff',
                        'flow-icon-btn': '5px 5px 10px #d4d4d4, -5px -5px 10px #ffffff',
                    }
                },
            },
        }
    </script>
<style>
        .material-symbols-outlined {
            font-variation-settings: 'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24;
        }
        .btn-press:active {
            box-shadow: inset 5px 5px 10px #d1d1d1, inset -5px -5px 10px #ffffff !important;
            transform: scale(0.97);
        }
        body {
            min-height: max(884px, 100dvh);
            background-color: #EFEEEE;
        }
        .flow-container-border {
            border: 1px solid rgba(255, 255, 255, 0.6);
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-bg font-display antialiased text-text-main overflow-hidden h-[100dvh] w-full flex flex-col relative selection:bg-primary/20">
<header class="relative z-30 flex items-center justify-center px-8 pt-14 pb-6">
<h1 class="text-xl font-bold text-slate-700 tracking-tight">拍照上传</h1>
</header>
<main class="flex-1 px-6 py-2 flex flex-col relative z-10 w-full max-w-md mx-auto">
<div class="w-full flex-1 rounded-[3rem] bg-bg shadow-flow-flat p-6 flex flex-col relative transition-all duration-300 flow-container-border">
<div class="relative w-full h-full bg-[#E8E7E7] rounded-[2.5rem] shadow-flow-pressed overflow-hidden border border-white/20 group">
<img alt="Camera Preview" class="absolute inset-0 w-full h-full object-cover opacity-90 mix-blend-multiply filter contrast-[1.05] brightness-105" src="https://lh3.googleusercontent.com/aida-public/AB6AXuAGwgwTsr07T-xsVoUN3qz4neyFhCUS7CB0IUTyea7vDJzQjWVjvRgTpPDMMY9W7abbvJGD-f8taGTvm8JW2qIBJ4Mwh-XYNQI7UxFD6UL4OjhqYfaAv8k_ijtKiQZ5wZi15QlHlYyMJofSCJY0HIs3ORp58XCPWXfqnPG46YnYtlRAHHf3VvMZurRckIcsPJV546HKBq_Ud8BixCTdEJ_Hh0uZBXxNf-4rlvnvPHkvBVmwBs9EEbfQpP87frF_gZbOgSjaxL9461I"/>
<div class="absolute inset-0 pointer-events-none p-6 opacity-80">
<div class="absolute top-8 left-8 w-12 h-12 border-t-[3px] border-l-[3px] border-white/80 rounded-tl-3xl shadow-sm"></div>
<div class="absolute top-8 right-8 w-12 h-12 border-t-[3px] border-r-[3px] border-white/80 rounded-tr-3xl shadow-sm"></div>
<div class="absolute bottom-8 left-8 w-12 h-12 border-b-[3px] border-l-[3px] border-white/80 rounded-bl-3xl shadow-sm"></div>
<div class="absolute bottom-8 right-8 w-12 h-12 border-b-[3px] border-r-[3px] border-white/80 rounded-br-3xl shadow-sm"></div>
<div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-8 h-8 opacity-70">
<div class="absolute top-1/2 left-0 w-full h-[1.5px] bg-white rounded-full shadow-sm"></div>
<div class="absolute left-1/2 top-0 h-full w-[1.5px] bg-white rounded-full shadow-sm"></div>
</div>
</div>
</div>
<div class="mt-6 mb-2 flex items-center justify-center gap-2">
<span class="w-2 h-2 rounded-full bg-primary/70 animate-pulse shadow-sm"></span>
<p class="text-slate-500 text-sm font-medium tracking-wide">请将作业平整置于框内</p>
</div>
</div>
</main>
<div class="relative w-full pb-12 pt-4 px-10 z-30 max-w-md mx-auto">
<div class="flex items-center justify-between">
<button class="flex flex-col items-center gap-3 group btn-press transition-all duration-200 w-20">
<div class="w-14 h-14 rounded-full bg-bg shadow-flow-icon-btn flex items-center justify-center text-slate-400 group-hover:text-primary transition-colors border border-white/50">
<span class="material-symbols-outlined text-[26px]">photo_library</span>
</div>
<span class="text-[11px] font-semibold text-slate-400 group-hover:text-slate-500 transition-colors">相册</span>
</button>
<button class="w-20 h-20 rounded-full bg-gradient-to-br from-white to-[#E5E5E5] shadow-flow-btn flex items-center justify-center -mt-6 active:scale-95 transition-all duration-300 border border-white/60 relative group">
<div class="w-16 h-16 rounded-full border-[3px] border-slate-200/50 group-active:border-primary/30 transition-all"></div>
<div class="absolute w-12 h-12 rounded-full bg-white shadow-sm group-active:scale-90 transition-transform duration-200"></div>
</button>
<button class="flex flex-col items-center gap-3 group btn-press transition-all duration-200 w-20">
<div class="w-14 h-14 rounded-full bg-bg shadow-flow-icon-btn flex items-center justify-center text-slate-400 group-hover:text-primary transition-colors border border-white/50">
<span class="material-symbols-outlined text-[26px]">home</span>
</div>
<span class="text-[11px] font-semibold text-slate-400 group-hover:text-slate-500 transition-colors">首页</span>
</button>
</div>
</div>

</body></html>

## 照片预览/上传页面
<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" name="viewport"/>
<title>首页 (已拍照片预览与上传)</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        bg: '#EFEEEE', // Updated to standard gray-white #EFEEEE
                        'shadow-light': '#FFFFFF',
                        'shadow-dark': '#D1D1D1', // Neutral gray for the new background
                        'text-main': '#444B59', 
                        'text-sub': '#6D7587',
                        'primary': '#6D5DFC', 
                        'accent': '#FFD074', 
                        'icon-gray': '#7D8699', 
                    },
                    fontFamily: {
                        "display": ["Lexend", "Noto Sans", "sans-serif"]
                    },
                    boxShadow: {
                        // Refined Shadows for #EFEEEE - Neutral and soft
                        'neu-flat': '9px 9px 16px rgb(180,180,180,0.6), -9px -9px 16px rgba(255,255,255, 0.6)',
                        'neu-flat-sm': '6px 6px 10px rgb(180,180,180,0.6), -6px -6px 10px rgba(255,255,255, 0.8)',
                        // Deep, soft pressed state
                        'neu-pressed': 'inset 6px 6px 10px 0 rgba(180,180,180, 0.7), inset -6px -6px 10px 0 rgba(255,255,255, 0.9)',
                        'neu-pressed-deep': 'inset 10px 10px 20px 0 rgba(180,180,180, 0.7), inset -10px -10px 20px 0 rgba(255,255,255, 0.9)',
                        // Floating button look
                        'neu-btn': '6px 6px 12px #c8c8c8, -6px -6px 12px #ffffff',
                        // Card lift
                        'card-lift': '20px 20px 60px #c8c8c8, -20px -20px 60px #ffffff',
                    },
                    borderRadius: {
                        'flow': '2.5rem', 
                    }
                },
            },
        }
    </script>
<style>
        body {
            background-color: #EFEEEE;color: #444B59;
        }
        .material-symbols-outlined {
            font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
        }
        .btn-press {
            transition: all 0.2s ease;
        }
        .btn-press:active {
            box-shadow: inset 4px 4px 8px rgba(180,180,180, 0.7), inset -4px -4px 8px rgba(255,255,255, 0.9);
            transform: scale(0.96);
        }.flow-ring {
            box-shadow: -2px -2px 5px rgba(255,255,255,1), 3px 3px 5px rgba(0,0,0,0.1);
        }.glass-overlay {
            background: linear-gradient(145deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0) 100%);
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="font-display antialiased overflow-hidden h-[100dvh] w-full flex flex-col relative selection:bg-primary/20">
<header class="relative z-30 flex items-center justify-between px-8 pt-14 pb-6">
<div class="w-10 h-10 rounded-full shadow-neu-flat-sm flex items-center justify-center text-text-sub opacity-0 pointer-events-none">
<span class="material-symbols-outlined text-[20px]">arrow_back</span>
</div>
<div class="flex flex-col items-center">
<div class="flex items-center gap-2 mb-1">
<span class="material-symbols-outlined text-accent text-[18px]" style="font-variation-settings: 'FILL' 1;">bolt</span>
<span class="text-xs font-bold text-text-sub tracking-widest uppercase">FLOW UPLOAD</span>
</div>
<h1 class="text-xl font-medium text-text-main tracking-tight">拍照上传</h1>
</div>
<div class="w-10 h-10 rounded-full shadow-neu-flat-sm flex items-center justify-center text-text-sub opacity-0 pointer-events-none">
<span class="material-symbols-outlined text-[20px]">settings</span>
</div>
</header>
<main class="flex-1 px-6 py-4 flex flex-col relative z-10 w-full max-w-md mx-auto justify-center">
<div class="w-full aspect-[3/4] rounded-flow bg-bg shadow-neu-flat p-6 flex flex-col relative transition-all duration-300">
<div class="relative w-full h-full rounded-[2rem] shadow-neu-pressed-deep overflow-hidden group bg-[#EFEEEE]">
<div class="absolute inset-0 border-[6px] border-[#EFEEEE] rounded-[2rem] z-20 pointer-events-none shadow-[inset_1px_1px_2px_rgba(255,255,255,0.3),_1px_1px_2px_rgba(180,180,180,0.3)]"></div>
<img alt="Photo Preview" class="absolute inset-0 w-full h-full object-cover z-10 opacity-90 mix-blend-multiply" src="https://lh3.googleusercontent.com/aida-public/AB6AXuAGwgwTsr07T-xsVoUN3qz4neyFhCUS7CB0IUTyea7vDJzQjWVjvRgTpPDMMY9W7abbvJGD-f8taGTvm8JW2qIBJ4Mwh-XYNQI7UxFD6UL4OjhqYfaAv8k_ijtKiQZ5wZi15QlHlYyMJofSCJY0HIs3ORp58XCPWXfqnPG46YnYtlRAHHf3VvMZurRckIcsPJV546HKBq_Ud8BixCTdEJ_Hh0uZBXxNf-4rlvnvPHkvBVmwBs9EEbfQpP87frF_gZbOgSjaxL9461I"/>
<div class="absolute inset-0 z-10 bg-gradient-to-t from-[#EFEEEE]/20 to-transparent pointer-events-none"></div>
</div>
<div class="mt-6 flex justify-center items-center">
<span class="text-2xl font-light text-text-main tracking-widest font-display">PREVIEW</span>
</div>
</div>
</main>
<div class="relative w-full pb-12 pt-4 px-8 z-30 max-w-md mx-auto">
<div class="flex items-center justify-center gap-12">
<button class="w-14 h-14 rounded-full bg-bg shadow-neu-flat-sm flex items-center justify-center btn-press text-text-sub hover:text-text-main">
<span class="material-symbols-outlined text-[24px]">replay</span>
</button>
<button class="w-24 h-24 rounded-full bg-bg shadow-neu-flat flex items-center justify-center btn-press text-text-sub relative group">
<div class="absolute inset-2 rounded-full border border-white/40 pointer-events-none"></div>
<span class="material-symbols-outlined text-[40px] group-hover:scale-110 transition-transform duration-200">cloud_upload</span>
</button>
<button class="w-14 h-14 rounded-full bg-bg shadow-neu-flat-sm flex items-center justify-center btn-press text-text-sub hover:text-text-main">
<span class="material-symbols-outlined text-[24px]">home</span>
</button>
</div>
<div class="flex justify-center gap-12 mt-4 text-[10px] font-bold tracking-widest text-text-sub uppercase opacity-60">
<span class="w-14 text-center">Retake</span>
<span class="w-24 text-center">Upload</span>
<span class="w-14 text-center">Home</span>
</div>
</div>
</body></html>

## 上传中
<!DOCTYPE html>
<html class="light" lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Smart Grading - Uploading State</title>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script>
      tailwind.config = {
        darkMode: "class",
        theme: {
          extend: {
            colors: {
              "neu-bg": "#EFEEEE", 
              "neu-text-main": "#323842",
              "neu-text-sub": "#8A94A6",
              "neu-accent": "#4F46E5",
              "neu-highlight": "#FFFFFF",
              "neu-shadow-dark": "#C9C9C9",
              "primary": "#3B82F6",
              "accent-yellow": "#FACC15",
            },
            fontFamily: {
              "display": ["Lexend", "Noto Sans SC", "sans-serif"]
            },
            boxShadow: {
              'neu-convex': '8px 8px 16px #C9C9C9, -8px -8px 16px #FFFFFF',
              'neu-concave': 'inset 6px 6px 12px #C9C9C9, inset -6px -6px 12px #FFFFFF',
              'neu-deep': '12px 12px 28px #BFBFBF, -12px -12px 28px #FFFFFF',
              'neu-button': '6px 6px 12px #C9C9C9, -6px -6px 12px #FFFFFF',
              'neu-button-pressed': 'inset 4px 4px 8px #C9C9C9, inset -4px -4px 8px #FFFFFF',
            },
            animation: {
              'scan-loop': 'scanLoop 2.5s ease-in-out infinite',
              'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
              'spin-slow': 'spin 8s linear infinite',
            },
            keyframes: {
              scanLoop: {
                '0%': { top: '0%', opacity: '0' },
                '10%': { opacity: '1' },
                '90%': { opacity: '1' },
                '100%': { top: '100%', opacity: '0' },
              }
            }
          },
        },
      }
    </script>
<style>
    body {
        background-color: #EFEEEE;
    }
    .scan-line {
        position: absolute;
        left: 0;
        width: 100%;
        height: 2px;
        background: linear-gradient(90deg, rgba(79, 70, 229, 0) 0%, rgba(79, 70, 229, 1) 50%, rgba(79, 70, 229, 0) 100%);
        box-shadow: 0 0 15px 2px rgba(79, 70, 229, 0.5);
        z-index: 20;
    }
    .scan-trail {
        position: absolute;
        left: 0;
        width: 100%;
        height: 100px;
        background: linear-gradient(to top, rgba(79, 70, 229, 0.1), transparent);
        top: -100px; 
        z-index: 10;
    }
    .ring-inset-shadow {
        box-shadow: inset 8px 8px 16px #C9C9C9, inset -8px -8px 16px #FFFFFF;
    }
    .soft-ring-container {
        position: relative;
        border-radius: 50%;
        background: #EFEEEE;
        box-shadow: 12px 12px 24px #C9C9C9, -12px -12px 24px #FFFFFF;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .soft-ring-container::before {
        content: '';
        position: absolute;
        inset: 12px;
        border-radius: 50%;
        background: #EFEEEE;
        box-shadow: inset 6px 6px 12px #C9C9C9, inset -6px -6px 12px #FFFFFF;
        z-index: 0;
    }.image-overlay-neumorphic {
        background: linear-gradient(135deg, rgba(239, 238, 238, 0.2), rgba(255, 255, 255, 0.1));
        backdrop-filter: blur(0px);
    }
</style>
<style>
    body {
      min-height: max(800px, 100dvh);
    }
</style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-neu-bg font-display text-neu-text-main overflow-hidden h-screen flex flex-col items-center">
<div class="w-full flex items-center p-6 justify-center z-20 shrink-0 relative">
<h2 class="text-neu-text-main text-lg font-bold tracking-tight text-center">智能批改</h2>
</div>
<div class="flex-1 flex flex-col items-center justify-center w-full px-6 relative z-10 max-w-md pb-12">
<div class="relative w-full p-6 rounded-[40px] bg-neu-bg shadow-neu-deep flex flex-col items-center mb-8">
<div class="flex items-center gap-2 mb-6 self-start px-2">
<span class="material-symbols-outlined text-accent-yellow animate-pulse-slow">bolt</span>
<span class="text-xs font-semibold text-neu-text-sub tracking-widest uppercase">AI Processing</span>
</div>
<div class="relative w-full aspect-[4/5] rounded-[28px] p-3 bg-neu-bg shadow-neu-concave mb-4 overflow-hidden">
<div class="relative w-full h-full rounded-[20px] overflow-hidden">
<img alt="Homework paper" class="w-full h-full object-cover opacity-90" src="https://lh3.googleusercontent.com/aida-public/AB6AXuCM9KvWkx8_Go-TNSI1ARWWR9Oe1kJqOD0EsqCzD7hvNq43zKknEg1qjS3s0YBsvReWdkyHgL9S4appjwGC29BaxpDsBykYYrCu5r1u0PJ9x0ICBbOyuXLuOulnMpn9WCtONqd-ffN8hZ-A1BsUjVtRORnQBZqALdhsAM-u_PHyj27XFpBf5AeZMsb2A7wL3q5Gh4jaGkc1YnuQYlpzMJzcgpQvX6H5vfl3AeE9eijJ9CtrVJcTPg93Dp7r60cHQtrGpofTRRaDIBA"/>
<div class="absolute inset-0 bg-neu-text-main/5 mix-blend-multiply"></div>
<div class="absolute inset-0 w-full h-full pointer-events-none overflow-hidden">
<div class="absolute w-full animate-scan-loop left-0 -top-10">
<div class="scan-line"></div>
<div class="scan-trail"></div>
</div>
</div>
<div class="absolute top-3 left-3 w-4 h-4 border-t-2 border-l-2 border-neu-accent/80 rounded-tl-sm"></div>
<div class="absolute top-3 right-3 w-4 h-4 border-t-2 border-r-2 border-neu-accent/80 rounded-tr-sm"></div>
<div class="absolute bottom-3 left-3 w-4 h-4 border-b-2 border-l-2 border-neu-accent/80 rounded-bl-sm"></div>
<div class="absolute bottom-3 right-3 w-4 h-4 border-b-2 border-r-2 border-neu-accent/80 rounded-br-sm"></div>
<div class="absolute top-4 left-0 right-0 flex justify-center z-20">
<div class="bg-neu-bg/80 backdrop-blur-md shadow-lg px-4 py-1.5 rounded-full flex items-center gap-2 border border-white/40">
<div class="w-2 h-2 rounded-full bg-neu-accent animate-pulse"></div>
<span class="text-[10px] text-neu-text-main font-bold tracking-widest uppercase">Uploading</span>
</div>
</div>
</div>
</div>
</div>
<div class="w-full flex flex-col items-center gap-6 mt-2 mb-10">
<div class="w-full max-w-[240px] flex flex-col items-center gap-2">
<div class="w-full h-4 rounded-full bg-neu-bg shadow-neu-concave p-1 relative overflow-hidden">
<div class="h-full rounded-full bg-neu-text-sub transition-all duration-300" style="width: 85%;"></div>
</div>
<div class="text-neu-text-sub font-bold text-sm tracking-widest">4S</div>
</div>
<div class="text-center space-y-2">
<h2 class="text-neu-text-main text-2xl font-bold tracking-tight">
                正在上传图片
            </h2>
</div>
<div class="flex items-center gap-8 mt-4">
<div class="flex flex-col items-center gap-2">
<button class="w-14 h-14 rounded-full bg-neu-bg shadow-neu-button flex items-center justify-center text-neu-text-sub active:shadow-neu-button-pressed active:text-neu-accent transition-all duration-200 group">
<span class="material-symbols-outlined text-2xl group-active:scale-95">home</span>
</button>
<span class="text-[10px] font-semibold text-neu-text-sub tracking-wider uppercase">HOME</span>
</div>
</div>
</div>
</div>

</body></html>

## 识别中
<!DOCTYPE html>
<html class="light" lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Smart Grading - Flow State Neumorphism</title>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script>
      tailwind.config = {
        darkMode: "class",
        theme: {
          extend: {
            colors: {
              "neu-bg": "#EFEEEE", 
              "neu-text-main": "#323842",
              "neu-text-sub": "#8A94A6",
              "neu-accent": "#4F46E5",
              "neu-highlight": "#FFFFFF",
              "neu-shadow-dark": "#C9CCD4",
              "primary": "#3B82F6",
              "accent-yellow": "#FACC15",
            },
            fontFamily: {
              "display": ["Lexend", "Noto Sans SC", "sans-serif"]
            },
            boxShadow: {
              'neu-convex': '8px 8px 16px #C9CCD4, -8px -8px 16px #FFFFFF',
              'neu-concave': 'inset 6px 6px 12px #C9CCD4, inset -6px -6px 12px #FFFFFF',
              'neu-deep': '12px 12px 28px #B8BCC6, -12px -12px 28px #FFFFFF',
              'neu-button': '6px 6px 12px #C9CCD4, -6px -6px 12px #FFFFFF',
              'neu-button-pressed': 'inset 4px 4px 8px #C9CCD4, inset -4px -4px 8px #FFFFFF',
            },
            animation: {
              'scan-loop': 'scanLoop 2.5s ease-in-out infinite',
              'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
              'spin-slow': 'spin 8s linear infinite',
            },
            keyframes: {
              scanLoop: {
                '0%': { top: '0%', opacity: '0' },
                '10%': { opacity: '1' },
                '90%': { opacity: '1' },
                '100%': { top: '100%', opacity: '0' },
              }
            }
          },
        },
      }
    </script>
<style>
    body {
        background-color: #EFEEEE;
    }
    .scan-line {
        position: absolute;
        left: 0;
        width: 100%;
        height: 2px;
        background: linear-gradient(90deg, rgba(79, 70, 229, 0) 0%, rgba(79, 70, 229, 1) 50%, rgba(79, 70, 229, 0) 100%);
        box-shadow: 0 0 15px 2px rgba(79, 70, 229, 0.5);
        z-index: 20;
    }
    .scan-trail {
        position: absolute;
        left: 0;
        width: 100%;
        height: 100px;
        background: linear-gradient(to top, rgba(79, 70, 229, 0.1), transparent);
        top: -100px; 
        z-index: 10;
    }
    .ring-inset-shadow {
        box-shadow: inset 8px 8px 16px #C9CCD4, inset -8px -8px 16px #FFFFFF;
    }
    .soft-ring-container {
        position: relative;
        border-radius: 50%;
        background: #EFEEEE;
        box-shadow: 12px 12px 24px #C9CCD4, -12px -12px 24px #FFFFFF;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .soft-ring-container::before {
        content: '';
        position: absolute;
        inset: 12px;
        border-radius: 50%;
        background: #EFEEEE;
        box-shadow: inset 6px 6px 12px #C9CCD4, inset -6px -6px 12px #FFFFFF;
        z-index: 0;
    }.image-overlay-neumorphic {
        background: linear-gradient(135deg, rgba(239, 238, 238, 0.2), rgba(255, 255, 255, 0.1));
        backdrop-filter: blur(0px);
    }
</style>
<style>
    body {
      min-height: max(800px, 100dvh);
    }
</style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-neu-bg font-display text-neu-text-main overflow-hidden h-screen flex flex-col items-center">
<div class="w-full flex items-center p-6 justify-center z-20 shrink-0 relative">
<h2 class="text-neu-text-main text-lg font-bold tracking-tight text-center">智能批改</h2>
</div>
<div class="flex-1 flex flex-col items-center justify-center w-full px-6 relative z-10 max-w-md pb-12">
<div class="relative w-full p-6 rounded-[40px] bg-neu-bg shadow-neu-deep flex flex-col items-center mb-8">
<div class="flex items-center gap-2 mb-6 self-start px-2">
<span class="material-symbols-outlined text-accent-yellow animate-pulse-slow">bolt</span>
<span class="text-xs font-semibold text-neu-text-sub tracking-widest uppercase">AI Processing</span>
</div>
<div class="relative w-full aspect-[4/5] rounded-[28px] p-3 bg-neu-bg shadow-neu-concave mb-4 overflow-hidden">
<div class="relative w-full h-full rounded-[20px] overflow-hidden">
<img alt="Homework paper" class="w-full h-full object-cover opacity-90" src="https://lh3.googleusercontent.com/aida-public/AB6AXuBtF2XC_jmrKtJMRIe4-9hecoUk4blpgvHbU-Gnrq2lGtDgJhgOWFa6J6bpPpc2sv-K0ESP1rIliDcJ5xO79nJLaBo-n79TWK4sSPMB1tV6r3Erl4wUlohCui6Ao3sYE3zPNhqGvqurW0hXUeazlwzJtjqAweeHuweEIx5_v7I6S0-OKaNB1q1nFV4Vw_dED51zyi04LF6vMJUZUare4WHjvv2vBZUdK-i1U4TQ8Swno4j3BtVhA3VJ4GgxEp9AawwDk-tdQ-ycngQ"/>
<div class="absolute inset-0 bg-neu-text-main/5 mix-blend-multiply"></div>
<div class="absolute inset-0 w-full h-full pointer-events-none overflow-hidden">
<div class="absolute w-full animate-scan-loop left-0 -top-10">
<div class="scan-line"></div>
<div class="scan-trail"></div>
</div>
</div>
<div class="absolute top-3 left-3 w-4 h-4 border-t-2 border-l-2 border-neu-accent/80 rounded-tl-sm"></div>
<div class="absolute top-3 right-3 w-4 h-4 border-t-2 border-r-2 border-neu-accent/80 rounded-tr-sm"></div>
<div class="absolute bottom-3 left-3 w-4 h-4 border-b-2 border-l-2 border-neu-accent/80 rounded-bl-sm"></div>
<div class="absolute bottom-3 right-3 w-4 h-4 border-b-2 border-r-2 border-neu-accent/80 rounded-br-sm"></div>
<div class="absolute top-4 left-0 right-0 flex justify-center z-20">
<div class="bg-neu-bg/80 backdrop-blur-md shadow-lg px-4 py-1.5 rounded-full flex items-center gap-2 border border-white/40">
<div class="w-2 h-2 rounded-full bg-neu-accent animate-pulse"></div>
<span class="text-[10px] text-neu-text-main font-bold tracking-widest uppercase">Scanning</span>
</div>
</div>
</div>
</div>
</div>
<div class="w-full flex flex-col items-center gap-6 mt-2 mb-10">
<div class="w-full max-w-[240px] flex flex-col items-center gap-2">
<div class="w-full h-4 rounded-full bg-neu-bg shadow-neu-concave p-1 relative overflow-hidden">
<div class="h-full rounded-full bg-neu-text-sub transition-all duration-300" style="width: 85%;"></div>
</div>
<span class="text-xl font-bold text-neu-text-main font-display mt-2">85<span class="text-sm">%</span></span>
</div>
<div class="text-center space-y-2">
<h2 class="text-neu-text-main text-2xl font-bold tracking-tight">
                正在识别题目...
            </h2>
<p class="text-neu-text-sub text-sm font-medium">
                AI 正在逐题扫描分析
            </p>
</div>
<div class="flex items-center gap-8 mt-4">
<div class="flex flex-col items-center gap-2">
<button class="w-14 h-14 rounded-full bg-neu-bg shadow-neu-button flex items-center justify-center text-neu-text-sub active:shadow-neu-button-pressed active:text-neu-accent transition-all duration-200 group">
<span class="material-symbols-outlined text-2xl group-active:scale-95">home</span>
</button>
<span class="text-[10px] font-semibold text-neu-text-sub tracking-wider uppercase">HOME</span>
</div>
</div>
</div>
</div>
</body></html>

## 占位卡生成中
<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>智能批改</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;family=Noto+Sans+SC:wght@300;400;500;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script>
    tailwind.config = {
        theme: {
            extend: {
                colors: {
                    // Refined palette for #EFEEEE background
                    "bg-neu": "#EFEEEE", 
                    "shadow-light": "#FFFFFF",
                    "shadow-dark": "#C5C9D2", // Adjusted to be clean yet retain a hint of cool tone
                    "primary": "#374151", 
                    "accent-yellow": "#FFD600",
                    "text-dark": "#1F2937",
                    "text-gray": "#64748B",
                    "progress-gray": "#94A3B8",
                },
                fontFamily: {
                    "display": ["Lexend", "Noto Sans SC", "sans-serif"]
                },
                boxShadow: {
                    // Refined Neumorphic shadows for #EFEEEE - Minimal and Pure
                    'neu-flat': '10px 10px 20px #C5C9D2, -10px -10px 20px #FFFFFF',
                    'neu-flat-sm': '5px 5px 10px #C5C9D2, -5px -5px 10px #FFFFFF',
                    'neu-pressed': 'inset 5px 5px 10px #C5C9D2, inset -5px -5px 10px #FFFFFF',
                    'neu-pressed-sm': 'inset 3px 3px 6px #C5C9D2, inset -3px -3px 6px #FFFFFF',
                    'neu-pressed-xs': 'inset 2px 2px 4px #C5C9D2, inset -2px -2px 4px #FFFFFF',
                    'neu-float': '16px 16px 32px #C5C9D2, -16px -16px 32px #FFFFFF',
                    'glow-yellow': '0 0 12px rgba(255, 214, 0, 0.4)',
                    'inner-light': 'inset 1px 1px 2px rgba(255,255,255,0.7)',
                },
                borderRadius: {
                    'xl': '1rem',
                    '2xl': '1.5rem',
                    '3xl': '2rem',
                }
            },
        },
    }
</script>
<style>
    body {
        background-color: #EFEEEE;
        min-height: max(884px, 100dvh);
    }
    .shimmer-bg {
        background: linear-gradient(90deg, #EFEEEE 0%, #E2E2E2 50%, #EFEEEE 100%);
        background-size: 200% 100%;
        animation: shimmer 1.5s infinite;
    }
    @keyframes shimmer {
        0% { background-position: 200% 0; }
        100% { background-position: -200% 0; }
    }
    .convex-card {
        background: linear-gradient(145deg, #FFFFFF, #E3E3E3);
    }
    .concave-surface {
        background: linear-gradient(145deg, #E3E3E3, #FFFFFF);
    }
    .text-pressed {
        color: transparent;
        text-shadow: 1px 1px 1px #FFFFFF, -1px -1px 1px #C5C9D2;
        background-color: #64748B;
        -webkit-background-clip: text;
        -moz-background-clip: text;
        background-clip: text;
        text-shadow: 2px 2px 4px rgba(255,255,255,0.5), -1px -1px 2px rgba(0,0,0,0.05);
    }
</style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="relative flex h-auto min-h-screen w-full flex-col overflow-x-hidden font-display text-text-dark bg-bg-neu pb-40">
<header class="sticky top-0 z-30 flex items-center justify-center p-4 bg-bg-neu/90 backdrop-blur-xl transition-all">
<h2 class="text-text-dark text-lg font-bold tracking-tight opacity-90">智能批改</h2>
</header>
<main class="flex-1 flex flex-col px-5 gap-7 mt-2">
<div class="convex-card rounded-[32px] p-7 shadow-neu-flat border border-white/40">
<div class="flex justify-between items-start mb-6">
<div class="flex flex-col gap-2">
<h2 class="text-text-dark text-2xl font-bold tracking-tight">本次作业批改中</h2>
<p class="text-text-gray text-sm font-medium tracking-wide">正在智能分析您的作业...</p>
</div>
<div class="flex items-center justify-center h-12 px-5 rounded-full shadow-neu-pressed bg-bg-neu">
<div class="flex items-baseline gap-1">
<span class="text-primary font-bold text-xl">1</span>
<span class="text-text-gray/80 text-xs font-semibold">/ 3 页</span>
</div>
</div>
</div>
<div class="flex flex-col gap-4">
<div class="flex justify-between text-xs font-bold text-primary px-1.5">
<span class="flex items-center gap-2.5">
<span class="relative flex h-3 w-3">
<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-yellow opacity-75"></span>
<span class="relative inline-flex rounded-full h-3 w-3 bg-accent-yellow shadow-glow-yellow"></span>
</span>
<span class="text-text-dark/70 tracking-wide">AI 正在思考</span>
</span>
<span class="text-primary font-extrabold">33%</span>
</div>
<div class="h-1.5 w-full rounded-full shadow-neu-pressed-xs bg-bg-neu p-0.5">
<div class="h-full bg-progress-gray/80 rounded-full w-1/3 relative overflow-hidden shadow-inner">
<div class="absolute inset-0 bg-white/40 w-full h-full animate-[shimmer_2s_infinite] skew-x-12 translate-x-[-100%]"></div>
</div>
</div>
</div>
</div>
<div class="flex items-center justify-between px-3 mt-1">
<span class="text-sm font-bold text-text-gray/90 tracking-widest uppercase">Page 1</span>
</div>
<div class="flex flex-col gap-6">
<div class="relative flex flex-col rounded-[28px] shadow-neu-flat convex-card overflow-hidden p-6 transition-transform active:scale-[0.99] border border-white/60">
<div class="absolute left-0 top-6 bottom-6 w-1.5 rounded-r-full bg-accent-yellow shadow-[0_0_12px_#FFD600]"></div>
<div class="flex items-start gap-5 pl-3">
<div class="flex-1 min-w-0">
<div class="flex items-center gap-4 mb-5">
<span class="inline-flex items-center justify-center rounded-xl px-0 py-1.5 text-xs font-bold text-text-dark">
                            第 1 题
                        </span>
<span class="inline-flex items-center gap-2 text-xs font-bold text-text-dark">
<span class="material-symbols-outlined text-[18px] text-accent-yellow animate-spin" style="text-shadow: 0 0 8px rgba(255, 214, 0, 0.6);">sync</span>
                            正在识别...
                        </span>
</div>
<div class="flex flex-col gap-4">
<div class="h-8 w-3/4 rounded-lg shadow-neu-pressed bg-bg-neu flex items-center px-4">
<span class="text-xs text-text-gray/60 font-medium">题目内容加载中...</span>
</div>
<div class="h-8 w-1/2 rounded-lg shadow-neu-pressed bg-bg-neu flex items-center px-4">
<span class="text-xs text-text-gray/60 font-medium">选项内容...</span>
</div>
</div>
</div>
</div>
</div>
<div class="flex flex-col rounded-[28px] shadow-neu-flat bg-bg-neu/80 p-6 opacity-80 border border-white/30 mix-blend-multiply">
<div class="flex items-start gap-5 pl-3">
<div class="flex-1 min-w-0">
<div class="flex items-center gap-4 mb-5">
<span class="inline-flex items-center justify-center rounded-xl px-0 py-1.5 text-xs font-bold text-text-gray">
                            第 2 题
                        </span>
<span class="inline-flex items-center gap-2 text-xs font-medium text-text-gray">
<span class="material-symbols-outlined text-[18px]">hourglass_empty</span>
                            等待分析
                        </span>
</div>
<div class="flex flex-col gap-4 opacity-70">
<div class="h-8 w-2/3 rounded-lg shadow-neu-pressed bg-bg-neu flex items-center px-4">
<span class="text-xs text-text-gray/50 font-medium">等待加载...</span>
</div>
<div class="h-8 w-1/3 rounded-lg shadow-neu-pressed bg-bg-neu flex items-center px-4">
<span class="text-xs text-text-gray/50 font-medium">等待加载...</span>
</div>
</div>
</div>
</div>
</div>
<div class="flex flex-col rounded-[28px] shadow-neu-flat bg-bg-neu/60 p-6 opacity-60 border border-white/20 mix-blend-multiply">
<div class="flex items-start gap-5 pl-3">
<div class="flex-1 min-w-0">
<div class="flex items-center gap-4 mb-5">
<span class="inline-flex items-center justify-center rounded-xl px-0 py-1.5 text-xs font-bold text-text-gray">
                            第 3 题
                        </span>
<span class="inline-flex items-center gap-2 text-xs font-medium text-text-gray">
<span class="material-symbols-outlined text-[18px]">hourglass_empty</span>
                            等待分析
                        </span>
</div>
<div class="flex flex-col gap-4 opacity-70">
<div class="h-8 w-2/3 rounded-lg shadow-neu-pressed bg-bg-neu flex items-center px-4">
<span class="text-xs text-text-gray/50 font-medium">等待加载...</span>
</div>
<div class="h-8 w-1/4 rounded-lg shadow-neu-pressed bg-bg-neu flex items-center px-4">
<span class="text-xs text-text-gray/50 font-medium">等待加载...</span>
</div>
</div>
</div>
</div>
</div>
</div>
</main>
<div class="fixed bottom-8 left-0 right-0 z-40 flex flex-col items-center justify-center gap-3 pointer-events-none">
<button class="convex-card pointer-events-auto flex size-20 items-center justify-center rounded-full shadow-neu-float text-gray-400 border border-white/60 transition-all hover:scale-105 active:scale-95 active:shadow-neu-pressed active:bg-transparent">
<span class="material-symbols-outlined text-[36px] text-gray-400">home</span>
</button>
<span class="text-[10px] font-bold text-text-gray/60 tracking-[0.2em] uppercase">Home</span>
</div>

</body></html>


## 占位卡完成
<html lang="zh-CN"><head><style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head><body class="relative flex h-auto min-h-screen w-full flex-col overflow-x-hidden font-display text-text-dark bg-bg-neu pb-32">```html



<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>智能批改</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;family=Noto+Sans+SC:wght@300;400;500;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script>
    tailwind.config = {
        theme: {
            extend: {
                colors: {
                    "bg-neu": "#EFEEEE", // Updated base color to match request
                    "shadow-light": "#FFFFFF",
                    "shadow-dark": "#C8CDD6", // Adjusted shadow for #EFEEEE
                    "primary": "#334155", 
                    "accent-yellow": "#FFD600",
                    "accent-green": "#34D399",
                    "accent-red": "#F87171",
                    "text-dark": "#1E293B",
                    "text-gray": "#64748B",
                    "progress-gray": "#94A3B8",
                },
                fontFamily: {
                    "display": ["Lexend", "Noto Sans SC", "sans-serif"]
                },
                boxShadow: {
                    // Refined Neumorphism shadows for #EFEEEE background
                    'neu-flat': '12px 12px 24px #C8CDD6, -12px -12px 24px #FFFFFF',
                    'neu-flat-sm': '5px 5px 10px #C8CDD6, -5px -5px 10px #FFFFFF',
                    'neu-pressed': 'inset 6px 6px 12px #C8CDD6, inset -6px -6px 12px #FFFFFF',
                    'neu-pressed-sm': 'inset 3px 3px 6px #C8CDD6, inset -3px -3px 6px #FFFFFF',
                    'neu-float': '16px 16px 32px #C8CDD6, -16px -16px 32px #FFFFFF',
                    'neu-concave': 'linear-gradient(145deg, #d9dbdf, #ffffff)', 
                    'neu-convex': 'linear-gradient(145deg, #ffffff, #d9dbdf)',
                    'glow-yellow': '0 0 12px rgba(255, 214, 0, 0.4)',
                    'glow-green': '0 0 12px rgba(52, 211, 153, 0.4)',
                    'glow-red': '0 0 12px rgba(248, 113, 113, 0.4)',
                }
            },
        },
    }
</script>
<style>
    body {
        background-color: #EFEEEE;
    }
    .shimmer-bg {
        background: linear-gradient(90deg, #EFEEEE 0%, #E3E6EB 50%, #EFEEEE 100%);
        background-size: 200% 100%;
        animation: shimmer 1.5s infinite;
    }
    @keyframes shimmer {
        0% { background-position: 200% 0; }
        100% { background-position: -200% 0; }
    }
    .neu-transition {
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
</style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
</style>


<header class="sticky top-0 z-30 flex items-center justify-between p-6 bg-bg-neu/80 backdrop-blur-lg transition-all">
<div class="size-10"></div>
<h2 class="text-text-dark text-xl font-bold tracking-tight opacity-90">智能批改</h2>
<div class="size-10"></div>
</header>
<main class="flex-1 flex flex-col px-6 gap-8 mt-2">
<div class="rounded-[32px] p-7 shadow-neu-flat bg-bg-neu border border-white/60 relative overflow-hidden group">
<div class="flex justify-between items-start mb-6">
<div class="flex flex-col gap-2">
<h2 class="text-text-dark text-2xl font-bold tracking-tight">本次作业批改中</h2>
<p class="text-text-gray text-sm font-medium opacity-80">正在智能分析您的作业...</p>
</div>
<div class="flex items-center justify-center h-12 px-5 rounded-full shadow-neu-pressed bg-bg-neu border border-white/20">
<div class="flex items-baseline gap-1.5">
<span class="text-primary font-bold text-xl">2</span>
<span class="text-text-gray text-xs font-semibold opacity-70">/ 3 页</span>
</div>
</div>
</div>
<div class="flex flex-col gap-4">
<div class="flex justify-between text-xs font-bold text-primary px-1 items-center">
<span class="flex items-center gap-2.5">
<span class="relative flex h-3 w-3">
<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-yellow opacity-60"></span>
<span class="relative inline-flex rounded-full h-3 w-3 bg-accent-yellow shadow-glow-yellow"></span>
</span>
<span class="text-text-dark/70 tracking-wide text-xs">AI 正在思考</span>
</span>
<span class="text-primary text-sm font-black opacity-80">66%</span>
</div>
<div class="h-2 w-full rounded-full shadow-neu-pressed bg-bg-neu p-[1px]">
<div class="h-full bg-progress-gray rounded-full w-2/3 relative overflow-hidden shadow-inner">
<div class="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 to-transparent w-full h-full animate-[shimmer_2s_infinite] skew-x-12 translate-x-[-100%]"></div>
</div>
</div>
</div>
</div>
<div class="flex items-center justify-between px-3 mt-2">
<span class="text-sm font-bold text-text-gray tracking-widest uppercase opacity-60">Page 1</span>
</div>
<div class="flex flex-col gap-6">
<div class="relative flex flex-col rounded-[28px] shadow-neu-flat bg-bg-neu overflow-hidden p-6 neu-transition active:scale-[0.98] border border-white/50">
<div class="absolute left-0 top-8 bottom-8 w-1.5 rounded-r-full bg-accent-green shadow-glow-green opacity-90"></div>
<div class="flex items-start gap-5 pl-3">
<div class="flex-1 min-w-0">
<div class="flex items-center gap-3 mb-4 pr-1">
<span class="text-sm font-bold text-text-dark/80 ml-1">
                                第 1 题
                            </span>
</div>
<div class="flex flex-col gap-3">
<div class="rounded-2xl p-5 shadow-neu-pressed bg-bg-neu border border-white/20">
<p class="text-[15px] text-text-gray leading-loose font-normal tracking-wide">
                                    已知集合 A={x | x²-2x-3 &lt; 0}，B={x | y=ln(2-x)}，则 A∩B = ?
                                </p>
</div>
</div>
</div>
</div>
</div>
<div class="relative flex flex-col rounded-[28px] shadow-neu-flat bg-bg-neu overflow-hidden p-6 border border-white/30">
<div class="absolute left-0 top-8 bottom-8 w-1.5 rounded-r-full bg-accent-red shadow-glow-red opacity-90"></div>
<div class="flex items-start gap-5 pl-3">
<div class="flex-1 min-w-0">
<div class="flex items-center gap-3 mb-4 pr-1">
<span class="text-sm font-bold text-text-dark/80 ml-1">
                                第 2 题
                            </span>
<button class="ml-auto flex size-9 items-center justify-center rounded-full bg-bg-neu shadow-neu-flat-sm border border-white/40 text-text-gray active:shadow-neu-pressed-sm active:scale-95 transition-all outline-none">
<div class="relative flex items-center justify-center">
<span class="material-symbols-outlined text-[24px]">chat_bubble</span>
<span class="absolute text-[8px] font-bold text-text-gray mt-[-2px]">AI</span>
</div>
</button>
</div>
<div class="flex flex-col gap-3">
<div class="rounded-2xl p-5 shadow-neu-pressed bg-bg-neu border border-white/20">
<p class="text-[15px] text-text-gray leading-loose font-normal tracking-wide">
                                    若复数 z 满足 (1+i)z = 2i，则 |z| 的值为多少？
                                </p>
</div>
</div>
</div>
</div>
</div>
</div>
</main>
<div class="fixed bottom-12 left-0 right-0 z-40 px-6 flex justify-center pointer-events-none">
<div class="pointer-events-auto flex flex-col items-center gap-4 cursor-pointer neu-transition active:scale-90 group">
<div class="flex size-20 items-center justify-center rounded-full bg-bg-neu shadow-neu-flat text-text-gray/50 group-active:shadow-neu-pressed group-active:text-text-gray/70 transition-all duration-300 border border-white/40 group-hover:text-primary relative overflow-hidden">
<div class="absolute inset-0 rounded-full bg-gradient-to-br from-white/40 to-transparent opacity-50 pointer-events-none"></div>
<span class="material-symbols-outlined text-[36px] z-10">home</span>
</div>
<span class="text-[10px] font-bold text-text-gray/50 tracking-[0.2em] group-hover:text-text-gray/80 transition-colors">HOME</span>
</div>
</div>

</body></html>

## 批改结果页面
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Activity Details - Flow State</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script>
    tailwind.config = {
        theme: {
            extend: {
                colors: {
                    "bg-flow": "#EFEEEE", // Updated to standard gray-white #EFEEEE
                    "tech-blue": "#3B82F6", 
                    "crimson-red": "#EF4444", 
                    "emerald-green": "#10B981", 
                    "text-dark": "#1F2937", 
                    "text-medium": "#6B7280", 
                    "amber-yellow": "#F59E0B", 
                },
                fontFamily: {
                    "display": ["Lexend", "sans-serif"]
                },
                boxShadow: {
                    // Refined shadows for #EFEEEE background to maintain depth without blue tint
                    'flow-base': '12px 12px 24px #D1D1D1, -12px -12px 24px #FFFFFF',
                    'flow-sm': '5px 5px 10px #D1D1D1, -5px -5px 10px #FFFFFF',
                    'flow-pressed': 'inset 6px 6px 12px #D1D1D1, -6px -6px 12px #FFFFFF',
                    'flow-icon': '4px 4px 8px #D1D1D1, -4px -4px 8px #FFFFFF',
                    'flow-btn': '8px 8px 16px #D1D1D1, -8px -8px 16px #FFFFFF',
                    'flow-float': '16px 16px 32px #C0C0C0, -16px -16px 32px #FFFFFF',
                },
                borderRadius: {
                    'flow': '2.5rem', 
                    'flow-sm': '1.5rem',
                }
            },
        },
    }
</script>
<style>
    .material-symbols-outlined {
        font-variation-settings: 'FILL' 1, 'wght' 500, 'GRAD' 0, 'opsz' 24;
    }
    .no-scrollbar::-webkit-scrollbar {
        display: none;
    }
    .no-scrollbar {
        -ms-overflow-style: none;
        scrollbar-width: none;
    }
    .snap-x-mandatory {
        scroll-snap-type: x mandatory;
    }
    .snap-center {
        scroll-snap-align: center;
    }
    body {
        background-color: #EFEEEE;
        min-height: max(884px, 100dvh);
    }
</style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-flow font-display antialiased text-text-dark selection:bg-tech-blue selection:text-white">
<div class="relative flex h-full min-h-screen w-full flex-col max-w-md mx-auto bg-flow overflow-hidden pb-4">
<header class="flex items-center px-6 py-6 justify-between sticky top-0 z-20 bg-flow/90 backdrop-blur-md">
<div class="w-12"></div>
<h2 class="text-xl font-bold text-text-dark tracking-tight opacity-90">批改结果</h2>
<button class="h-12 w-12 flex items-center justify-center rounded-full bg-flow shadow-flow-icon text-text-medium active:shadow-flow-pressed active:scale-95 transition-all duration-300">
<span class="material-symbols-outlined text-[1.35rem]">share</span>
</button>
</header>
<section class="px-6 pt-2 pb-6">
<div class="bg-flow rounded-[2.5rem] p-8 shadow-flow-base relative overflow-hidden transition-all duration-300 z-10 border border-white/40">
<div class="relative z-10 flex justify-between items-center mb-10">
<div>
<div class="text-sm text-text-medium font-medium mb-1.5 opacity-80">作业编号：</div>
<span class="text-xl font-bold text-text-dark tracking-wider pl-1">#84021</span>
</div>
<div class="h-20 w-20 rounded-full bg-flow border-4 border-[#FCD34D] shadow-flow-sm flex items-center justify-center relative group">
<span class="text-3xl font-bold text-emerald-green relative z-10">A-</span>
</div>
</div>
<div class="grid grid-cols-3 gap-6 pt-2">
<div class="flex flex-col items-center group gap-3">
<div class="h-14 w-14 rounded-full bg-flow shadow-flow-icon flex items-center justify-center text-gray-400 group-active:shadow-flow-pressed transition-all duration-300 border border-white/30">
<span class="material-symbols-outlined text-2xl">check_circle</span>
</div>
<div class="text-lg font-bold text-text-dark opacity-90">18</div>
</div>
<div class="flex flex-col items-center group gap-3">
<div class="h-14 w-14 rounded-full bg-flow shadow-flow-icon flex items-center justify-center text-gray-400 group-active:shadow-flow-pressed transition-all duration-300 border border-white/30">
<span class="material-symbols-outlined text-2xl">cancel</span>
</div>
<div class="text-lg font-bold text-text-dark opacity-90">2</div>
</div>
<div class="flex flex-col items-center group gap-3">
<div class="h-14 w-14 rounded-full bg-flow shadow-flow-icon flex items-center justify-center text-gray-400 group-active:shadow-flow-pressed transition-all duration-300 border border-white/30">
<span class="material-symbols-outlined text-2xl">warning</span>
</div>
<div class="text-lg font-bold text-text-dark opacity-90">0</div>
</div>
</div>
</div>
</section>
<section class="flex-1 flex flex-col min-h-0 relative">
<div class="px-6 mb-6 flex justify-between items-center">
<h3 class="font-bold text-xl text-text-dark pl-2 opacity-90">错题详情</h3>
</div>
<div class="flex-1 overflow-x-auto snap-x-mandatory no-scrollbar flex items-start gap-6 px-6 pb-2 h-full z-10">
<div class="snap-center shrink-0 w-[85%] max-w-[320px] h-full flex flex-col py-2">
<div class="relative flex-1 flex flex-col bg-flow rounded-[2.5rem] shadow-flow-base overflow-hidden group hover:shadow-flow-float transition-all duration-300 border border-white/40">
<div class="flex-1 flex flex-col p-7">
<div class="flex justify-between items-start mb-6">
<h3 class="font-display font-bold text-3xl text-text-dark opacity-90">Q3</h3>
<span class="flex items-center gap-1.5 text-xs font-bold text-crimson-red bg-flow px-3 py-1.5 rounded-xl shadow-flow-pressed">
                                Wrong
                            </span>
</div>
<div class="flex-1 mb-8 bg-flow rounded-[1.5rem] p-5 shadow-flow-pressed border-b border-white/20">
<div class="mb-3">
<span class="text-[10px] font-bold text-text-medium uppercase tracking-widest opacity-70">AI Diagnosis</span>
</div>
<p class="text-[15px] text-text-medium leading-relaxed">
                                Calculation error in step 2. You forgot to distribute the negative sign: <span class="font-mono text-xs text-crimson-red font-bold px-1">-(3x + 2)</span>.
                            </p>
</div>
<div class="mt-auto">
<button class="w-full flex items-center justify-center gap-2 bg-flow text-text-medium py-4 rounded-2xl font-bold text-sm shadow-flow-btn active:scale-[0.98] active:shadow-flow-pressed transition-all duration-300 border border-white/40">
                                问问AI
                            </button>
</div>
</div>
</div>
</div>
<div class="snap-center shrink-0 w-[85%] max-w-[320px] h-full flex flex-col py-2">
<div class="relative flex-1 flex flex-col bg-flow rounded-[2.5rem] shadow-flow-base overflow-hidden border border-white/40">
<div class="flex-1 flex flex-col p-7">
<div class="flex justify-between items-start mb-6">
<h3 class="font-display font-bold text-3xl text-text-dark opacity-90">Q8</h3>
<span class="flex items-center gap-1.5 text-xs font-bold text-crimson-red bg-flow px-3 py-1.5 rounded-xl shadow-flow-pressed">
                                Wrong
                            </span>
</div>
<div class="flex-1 mb-8 bg-flow rounded-[1.5rem] p-5 shadow-flow-pressed border-b border-white/20">
<div class="mb-3">
<span class="text-[10px] font-bold text-text-medium uppercase tracking-widest opacity-70">AI Diagnosis</span>
</div>
<p class="text-[15px] text-text-medium leading-relaxed">
                                Concept misunderstanding. The formula for the area of a trapezoid is <span class="italic font-semibold text-text-dark">((a+b)/2) * h</span>.
                            </p>
</div>
<div class="mt-auto">
<button class="w-full flex items-center justify-center gap-2 bg-flow text-text-medium py-4 rounded-2xl font-bold text-sm shadow-flow-btn active:scale-[0.98] active:shadow-flow-pressed transition-all duration-300 border border-white/40">
                                问问AI
                            </button>
</div>
</div>
</div>
</div>
<div class="snap-center shrink-0 w-[85%] max-w-[320px] h-full flex flex-col py-2">
<div class="relative flex-1 flex flex-col bg-flow rounded-[2.5rem] shadow-flow-base overflow-hidden border border-white/40">
<div class="absolute left-0 top-0 bottom-0 w-2.5 bg-emerald-green"></div>
<div class="flex-1 flex flex-col p-7 pl-9">
<div class="flex justify-between items-start mb-6">
<h3 class="font-display font-bold text-3xl text-text-dark opacity-90">Q1</h3>
<span class="flex items-center gap-1.5 text-xs font-bold text-emerald-green bg-flow px-3 py-1.5 rounded-xl shadow-flow-pressed">
<span class="material-symbols-outlined !text-sm">check</span>
                                Correct
                            </span>
</div>
<div class="w-full bg-flow rounded-[1.5rem] overflow-hidden mb-6 shadow-flow-pressed relative aspect-[16/9] flex items-center justify-center border-b border-white/20">
<span class="text-xs text-text-medium font-medium">Question Preview</span>
</div>
<div class="flex-1 mb-8 flex items-center justify-center">
<div class="text-center">
<div class="w-16 h-16 rounded-full bg-flow shadow-flow-sm text-emerald-green flex items-center justify-center mx-auto mb-4 border border-white/50">
<span class="material-symbols-outlined !text-3xl">thumb_up</span>
</div>
<p class="text-sm text-text-medium font-medium">
                                    Great job! You solved this correctly.
                                </p>
</div>
</div>
<div class="mt-auto">
<button class="w-full flex items-center justify-center gap-2 bg-flow text-text-medium py-4 rounded-2xl font-bold text-sm shadow-flow-btn active:shadow-flow-pressed transition-all duration-300 border border-white/40">
                                View Details
                            </button>
</div>
</div>
</div>
</div>
<div class="w-2 shrink-0"></div>
</div>
</section>
<div class="pb-10 -mt-4 relative z-20">
<div class="flex justify-center pt-8">
<button class="h-[4.5rem] w-[4.5rem] rounded-full bg-flow shadow-flow-float flex items-center justify-center text-gray-400 active:shadow-flow-pressed active:scale-95 transition-all duration-300 border border-white/40">
<span class="material-symbols-outlined text-3xl">home</span>
</button>
</div>
</div>
</div>
</body></html>

# 题目详情
## 题目详情（有图）
<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>题目详情页</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;family=Noto+Sans+SC:wght@300;400;500;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script>
    tailwind.config = {
        theme: {
            extend: {
                colors: {
                    "bg-neu": "#EFEEEE","shadow-light": "#FFFFFF",
                    "shadow-dark": "#C8D0E0","primary": "#334155", 
                    "accent-yellow": "#FFD600",
                    "accent-green": "#34D399",
                    "accent-red": "#F87171",
                    "accent-blue": "#3B82F6",
                    "text-dark": "#1E293B",
                    "text-gray": "#64748B",
                    "progress-gray": "#94A3B8",
                },
                fontFamily: {
                    "display": ["Lexend", "Noto Sans SC", "sans-serif"]
                },
                boxShadow: {
                    'neu-flat': '12px 12px 20px #C8D0E0, -10px -10px 20px #FFFFFF','neu-flat-sm': '5px 5px 10px #C8D0E0, -5px -5px 10px #FFFFFF',
                    'neu-pressed': 'inset 6px 6px 12px #C8D0E0, inset -6px -6px 12px #FFFFFF',
                    'neu-pressed-sm': 'inset 3px 3px 6px #C8D0E0, inset -3px -3px 6px #FFFFFF',
                    'neu-float': '16px 16px 32px #C8D0E0, -16px -16px 32px #FFFFFF',
                    'glow-red': '0 0 12px rgba(248, 113, 113, 0.4)',
                    'glow-blue': '0 0 12px rgba(59, 130, 246, 0.4)',
                }
            },
        },
    }
</script>
<style>
    body {
        background-color: #EFEEEE;min-height: max(884px, 100dvh);
    }
    .neu-transition {
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    @keyframes shimmer {
        0% { transform: translateX(-150%); }
        100% { transform: translateX(150%); }
    }
    .animate-shimmer {
        animation: shimmer 2s infinite;
    }
</style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="relative flex h-auto min-h-screen w-full flex-col overflow-x-hidden font-display text-text-dark bg-bg-neu pb-32">
<header class="sticky top-0 z-30 flex items-center justify-between p-6 bg-bg-neu/80 backdrop-blur-lg transition-all">
<button class="size-10 flex items-center justify-center rounded-full text-text-gray/70 hover:text-text-dark active:scale-95 transition-transform bg-bg-neu shadow-neu-flat-sm border border-white/40">
<span class="material-symbols-outlined">chevron_left</span>
</button>
<h2 class="text-text-dark text-xl font-bold tracking-tight opacity-90">题目 Q1</h2>
<div class="size-10"></div>
</header>
<main class="flex-1 flex flex-col px-6 gap-6 mt-2">
<div class="relative flex flex-col rounded-[32px] shadow-neu-flat bg-bg-neu border border-white/60 overflow-hidden p-6 group">
<div class="absolute left-0 top-8 bottom-8 w-1.5 rounded-r-full bg-accent-red shadow-glow-red opacity-90"></div>
<div class="flex flex-col gap-5 pl-3">
<div class="flex justify-between items-center mb-1">
<span class="text-sm font-bold text-text-gray tracking-wider uppercase opacity-80 flex items-center gap-2">
<span class="material-symbols-outlined text-[18px]">quiz</span>
                    原题内容
                </span>
<span class="px-4 py-1.5 rounded-full shadow-neu-pressed-sm bg-bg-neu text-accent-red text-xs font-bold flex items-center justify-center">
                    错题
                </span>
</div>
<div class="rounded-2xl p-6 shadow-neu-pressed bg-bg-neu border border-white/20">
<p class="text-[16px] text-text-dark leading-relaxed font-medium tracking-wide">
                    已知集合 A={x | x²-2x-3 &lt; 0}，B={x | y=ln(2-x)}，则 A∩B = ?
                </p>
</div>
</div>
</div>
<div class="relative flex flex-col items-center justify-center rounded-[32px] shadow-neu-flat bg-bg-neu border border-white/60 p-6">
<div class="w-full rounded-2xl p-2.5 shadow-neu-pressed bg-bg-neu border border-white/10 flex items-center justify-center">
<div class="relative w-full overflow-hidden rounded-xl border border-white/80 ring-1 ring-white/30">
<img alt="几何题示意图" class="w-full h-48 object-cover mix-blend-multiply opacity-95" src="https://lh3.googleusercontent.com/aida-public/AB6AXuBzvpE3ijDdQw17zgV3mxgrpP7xM98Q8kKtzRb3q2k5jalPNN5ZCdEv8-EoWJkoRukXOZG6-MphIDGcXXeGnD2OdAvRoD44RXTY3bJXIN6eTZ-jaOYGgKw3pKHxrI01AB8PpKyzkOxFYULNPb0p3mljud0iIPGeTRoeZdADGq_qYP9j6nb4BEd90Bwaz0qJ7OMLrOWYdA-5p-vu8g0A5B3PbmiQNSI6oueTQCf66Gz6GsaoiOdRjqw8sETZQGWFOedrvVtt019MsEs"/>
</div>
</div>
</div>
<div class="relative flex flex-col rounded-[32px] shadow-neu-flat bg-bg-neu border border-white/60 overflow-hidden p-6 gap-6">
<div class="flex items-center gap-3">
<div class="flex items-center justify-center size-10 text-text-gray">
<span class="material-symbols-outlined text-[28px]">auto_awesome</span>
</div>
<h3 class="text-lg font-bold text-text-dark">AI 深度解析</h3>
</div>
<div class="rounded-2xl p-6 shadow-neu-pressed bg-bg-neu border border-white/20 flex flex-col gap-4">
<div>
<span class="text-xs font-bold text-text-gray/60 uppercase tracking-wider mb-2 block">解题思路</span>
<p class="text-[14px] text-text-gray leading-loose">
                    首先解不等式 <span class="font-mono text-primary bg-white/50 px-1 rounded">x²-2x-3 &lt; 0</span>，因式分解得 <span class="font-mono text-primary">(x-3)(x+1) &lt; 0</span>，故集合 A 为 <span class="font-mono text-primary">(-1, 3)</span>。<br/>
                    其次，由对数函数定义域 <span class="font-mono text-primary">2-x &gt; 0</span> 得集合 B 为 <span class="font-mono text-primary">x &lt; 2</span>。<br/>
                    最后求交集 A∩B，即 <span class="font-mono text-primary">(-1, 2)</span>。
                </p>
</div>
<div class="w-full h-px bg-text-gray/10"></div>
<div>
<span class="text-xs font-bold text-accent-red uppercase tracking-wider mb-2 block flex items-center gap-1">
<span class="material-symbols-outlined text-[14px]">error</span>
                    错误原因
                </span>
<p class="text-[13px] text-text-gray leading-relaxed">
                    在解二次不等式时符号判断错误，导致集合 A 的范围计算出现偏差。建议复习“一元二次不等式解法”。
                </p>
</div>
</div>
<div class="flex flex-wrap gap-3">
<span class="px-4 py-2 rounded-full shadow-neu-pressed-sm bg-bg-neu text-xs font-semibold text-text-gray hover:text-primary transition-colors cursor-default">
                # 集合运算
            </span>
<span class="px-4 py-2 rounded-full shadow-neu-pressed-sm bg-bg-neu text-xs font-semibold text-text-gray hover:text-primary transition-colors cursor-default">
                # 一元二次不等式
            </span>
<span class="px-4 py-2 rounded-full shadow-neu-pressed-sm bg-bg-neu text-xs font-semibold text-text-gray hover:text-primary transition-colors cursor-default">
                # 函数定义域
            </span>
</div>
<div class="pt-2 flex gap-4">
<button class="flex-1 py-4 rounded-2xl bg-bg-neu shadow-neu-flat border border-white/40 flex items-center justify-center text-text-gray font-bold active:shadow-neu-pressed active:scale-[0.98] transition-all hover:text-text-dark">
<span class="text-sm tracking-wide">错题排除</span>
</button>
<button class="flex-1 py-4 rounded-2xl bg-bg-neu shadow-neu-flat border border-white/40 flex items-center justify-center gap-2.5 text-primary font-bold active:shadow-neu-pressed active:scale-[0.98] transition-all group relative overflow-hidden">
<div class="absolute inset-0 bg-gradient-to-r from-transparent via-white/30 to-transparent skew-x-[-12deg] group-hover:animate-shimmer w-1/2 h-full opacity-0 group-hover:opacity-100 pointer-events-none"></div>
<span class="text-sm tracking-wide text-text-dark/80 group-hover:text-text-dark transition-colors">问问 AI</span>
</button>
</div>
</div>
</main>
<div class="fixed bottom-12 left-0 right-0 z-40 px-6 flex justify-center pointer-events-none">
<div class="pointer-events-auto flex flex-col items-center gap-4 cursor-pointer neu-transition active:scale-90 group">
<div class="flex size-20 items-center justify-center rounded-full bg-bg-neu shadow-neu-flat text-text-gray/50 group-active:shadow-neu-pressed group-active:text-text-gray/70 transition-all duration-300 border border-white/40 group-hover:text-primary relative overflow-hidden">
<div class="absolute inset-0 rounded-full bg-gradient-to-br from-white/40 to-transparent opacity-50 pointer-events-none"></div>
<span class="material-symbols-outlined text-[36px] z-10">home</span>
</div>
<span class="text-[10px] font-bold text-text-gray/50 tracking-[0.2em] group-hover:text-text-gray/80 transition-colors">HOME</span>
</div>
</div>

</body></html>

## 题目详情（无图）
<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>题目详情页</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;family=Noto+Sans+SC:wght@300;400;500;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script>
    tailwind.config = {
        theme: {
            extend: {
                colors: {
                    "bg-neu": "#EFEEEE", // Unified Background Color: #EFEEEE
                    "shadow-light": "#FFFFFF",
                    "shadow-dark": "#D1D5DB", // Optimized shadow color for #EFEEEE (Clean Grey)
                    "primary": "#334155", 
                    "accent-yellow": "#FFD600",
                    "accent-green": "#34D399",
                    "accent-red": "#F87171",
                    "accent-blue": "#3B82F6",
                    "text-dark": "#1E293B",
                    "text-gray": "#64748B",
                    "progress-gray": "#94A3B8",
                },
                fontFamily: {
                    "display": ["Lexend", "Noto Sans SC", "sans-serif"]
                },
                boxShadow: {
                    // Optimized shadows for minimalist look on #EFEEEE
                    'neu-flat': '10px 10px 20px #D1D5DB, -10px -10px 20px #FFFFFF',
                    'neu-flat-sm': '5px 5px 10px #D1D5DB, -5px -5px 10px #FFFFFF',
                    'neu-pressed': 'inset 6px 6px 12px #D1D5DB, inset -6px -6px 12px #FFFFFF',
                    'neu-pressed-sm': 'inset 3px 3px 6px #D1D5DB, inset -3px -3px 6px #FFFFFF',
                    'neu-float': '16px 16px 32px #D1D5DB, -16px -16px 32px #FFFFFF',
                    'glow-red': '0 0 12px rgba(248, 113, 113, 0.4)',
                    'glow-blue': '0 0 12px rgba(59, 130, 246, 0.4)',
                }
            },
        },
    }
</script>
<style>
    body {
        background-color: #EFEEEE;min-height: max(884px, 100dvh);
    }
    .neu-transition {
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    @keyframes shimmer {
        0% { transform: translateX(-150%); }
        100% { transform: translateX(150%); }
    }
    .animate-shimmer {
        animation: shimmer 2s infinite;
    }
</style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="relative flex h-auto min-h-screen w-full flex-col overflow-x-hidden font-display text-text-dark bg-bg-neu pb-32">
<header class="sticky top-0 z-30 flex items-center justify-between p-6 bg-bg-neu/80 backdrop-blur-lg transition-all">
<button class="size-10 flex items-center justify-center rounded-full text-text-gray/70 hover:text-text-dark active:scale-95 transition-transform bg-bg-neu shadow-neu-flat-sm border border-white/50">
<span class="material-symbols-outlined">chevron_left</span>
</button>
<h2 class="text-text-dark text-xl font-bold tracking-tight opacity-90">题目 Q1</h2>
<div class="size-10"></div>
</header>
<main class="flex-1 flex flex-col px-6 gap-6 mt-2">
<div class="relative flex flex-col rounded-[32px] shadow-neu-flat bg-bg-neu border border-white/50 overflow-hidden p-6 group">
<div class="absolute left-0 top-8 bottom-8 w-1.5 rounded-r-full bg-accent-red shadow-glow-red opacity-90"></div>
<div class="flex flex-col gap-5 pl-3">
<div class="flex justify-between items-center mb-1">
<span class="text-sm font-bold text-text-gray tracking-wider uppercase opacity-80 flex items-center gap-2">
<span class="material-symbols-outlined text-[18px]">quiz</span>
                    原题内容
                </span>
<span class="px-4 py-1.5 rounded-full shadow-neu-pressed-sm bg-bg-neu text-accent-red text-xs font-bold flex items-center justify-center">
                    错题
                </span>
</div>
<div class="rounded-2xl p-6 shadow-neu-pressed bg-bg-neu border border-white/20">
<p class="text-[16px] text-text-dark leading-relaxed font-medium tracking-wide">
                    已知集合 A={x | x²-2x-3 &lt; 0}，B={x | y=ln(2-x)}，则 A∩B = ?
                </p>
</div>
</div>
</div>
<div class="relative flex flex-col rounded-[32px] shadow-neu-flat bg-bg-neu border border-white/50 overflow-hidden p-6 gap-6">
<div class="flex items-center gap-3">
<div class="flex items-center justify-center size-10 text-text-gray">
<span class="material-symbols-outlined text-[28px]">auto_awesome</span>
</div>
<h3 class="text-lg font-bold text-text-dark">AI 深度解析</h3>
</div>
<div class="rounded-2xl p-6 shadow-neu-pressed bg-bg-neu border border-white/20 flex flex-col gap-4">
<div>
<span class="text-xs font-bold text-text-gray/60 uppercase tracking-wider mb-2 block">解题思路</span>
<p class="text-[14px] text-text-gray leading-loose">
                    首先解不等式 <span class="font-mono text-primary bg-white/50 px-1 rounded">x²-2x-3 &lt; 0</span>，因式分解得 <span class="font-mono text-primary">(x-3)(x+1) &lt; 0</span>，故集合 A 为 <span class="font-mono text-primary">(-1, 3)</span>。<br/>
                    其次，由对数函数定义域 <span class="font-mono text-primary">2-x &gt; 0</span> 得集合 B 为 <span class="font-mono text-primary">x &lt; 2</span>。<br/>
                    最后求交集 A∩B，即 <span class="font-mono text-primary">(-1, 2)</span>。
                </p>
</div>
<div class="w-full h-px bg-text-gray/10"></div>
<div>
<span class="text-xs font-bold text-accent-red uppercase tracking-wider mb-2 block flex items-center gap-1">
<span class="material-symbols-outlined text-[14px]">error</span>
                    错误原因
                </span>
<p class="text-[13px] text-text-gray leading-relaxed">
                    在解二次不等式时符号判断错误，导致集合 A 的范围计算出现偏差。建议复习“一元二次不等式解法”。
                </p>
</div>
</div>
<div class="flex flex-wrap gap-3">
<span class="px-4 py-2 rounded-full shadow-neu-pressed-sm bg-bg-neu text-xs font-semibold text-text-gray hover:text-primary transition-colors cursor-default">
                # 集合运算
            </span>
<span class="px-4 py-2 rounded-full shadow-neu-pressed-sm bg-bg-neu text-xs font-semibold text-text-gray hover:text-primary transition-colors cursor-default">
                # 一元二次不等式
            </span>
<span class="px-4 py-2 rounded-full shadow-neu-pressed-sm bg-bg-neu text-xs font-semibold text-text-gray hover:text-primary transition-colors cursor-default">
                # 函数定义域
            </span>
</div>
<div class="pt-2 flex gap-4">
<button class="flex-1 py-4 rounded-2xl bg-bg-neu shadow-neu-flat border border-white/40 flex items-center justify-center text-text-gray font-bold active:shadow-neu-pressed active:scale-[0.98] transition-all hover:text-text-dark">
<span class="text-sm tracking-wide">错题排除</span>
</button>
<button class="flex-1 py-4 rounded-2xl bg-bg-neu shadow-neu-flat border border-white/40 flex items-center justify-center gap-2.5 text-primary font-bold active:shadow-neu-pressed active:scale-[0.98] transition-all group relative overflow-hidden">
<div class="absolute inset-0 bg-gradient-to-r from-transparent via-white/30 to-transparent skew-x-[-12deg] group-hover:animate-shimmer w-1/2 h-full opacity-0 group-hover:opacity-100 pointer-events-none"></div>
<span class="text-sm tracking-wide text-text-dark/80 group-hover:text-text-dark transition-colors">问问 AI</span>
</button>
</div>
</div>
</main>
<div class="fixed bottom-12 left-0 right-0 z-40 px-6 flex justify-center pointer-events-none">
<div class="pointer-events-auto flex flex-col items-center gap-4 cursor-pointer neu-transition active:scale-90 group">
<div class="flex size-20 items-center justify-center rounded-full bg-bg-neu shadow-neu-flat text-text-gray/50 group-active:shadow-neu-pressed group-active:text-text-gray/70 transition-all duration-300 border border-white/40 group-hover:text-primary relative overflow-hidden">
<div class="absolute inset-0 rounded-full bg-gradient-to-br from-white/40 to-transparent opacity-50 pointer-events-none"></div>
<span class="material-symbols-outlined text-[36px] z-10">home</span>
</div>
<span class="text-[10px] font-bold text-text-gray/50 tracking-[0.2em] group-hover:text-text-gray/80 transition-colors">HOME</span>
</div>
</div>

</body></html>

# AI辅导页面
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>AI Tutor Chat Details</title>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif:ital,wght@0,400;0,700;1,400&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script id="tailwind-config">
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        "primary": "#4A6CF7",
                        "page-bg": "#EFEEEE", 
                        "text-main": "#2B3648",   
                        "text-muted": "#7A8699",
                        "accent-yellow": "#FFD600",
                        "math-bg-light": "#F7F7F7",     
                    },
                    fontFamily: {
                        "display": ["Lexend", "sans-serif"],
                        "math": ["Noto Serif", "serif"],
                    },
                    boxShadow: {
                        // Adjusted shadows for #EFEEEE background
                        // Using a neutral grey for shadows to match the unified background
                        'neu-flat': '8px 8px 16px #c6c6c6, -8px -8px 16px #ffffff',
                        'neu-flat-sm': '5px 5px 10px #c6c6c6, -5px -5px 10px #ffffff',
                        'neu-pressed': 'inset 4px 4px 8px #c6c6c6, inset -4px -4px 8px #ffffff',
                        // AI Bubble: Convex (Pop-out), Soft
                        'bubble-ai': '8px 8px 16px #c6c6c6, -8px -8px 16px #ffffff',
                        // User Bubble: Concave (Pressed-in)
                        'bubble-user': 'inset 6px 6px 12px #c6c6c6, inset -6px -6px 12px #ffffff',
                        // Send Button: Convex High (Pop-out)
                        'bubble-send': '6px 6px 12px #c6c6c6, -6px -6px 12px #ffffff',
                        // Input Field: Concave Soft
                        'input-inner': 'inset 4px 4px 8px #d1d1d1, inset -4px -4px 8px #ffffff',
                    }
                },
            },
        }
    </script>
<style>
        .no-scrollbar::-webkit-scrollbar { display: none; }
        .no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
        body { min-height: max(884px, 100dvh); }
        .mask-gradient {
            -webkit-mask-image: linear-gradient(to right, transparent, black 10px, black 90%, transparent);
            mask-image: linear-gradient(to right, transparent, black 10px, black 90%, transparent);
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-page-bg font-display antialiased overflow-hidden h-screen flex flex-col text-text-main">
<div class="flex items-center bg-page-bg p-4 pb-2 justify-between shrink-0 z-20">
<button class="text-text-main flex size-10 shrink-0 items-center justify-center rounded-full shadow-neu-flat-sm active:shadow-neu-pressed transition-all bg-page-bg hover:text-primary">
<span class="material-symbols-outlined text-xl">close</span>
</button>
<h2 class="text-text-main text-lg font-bold leading-tight tracking-[-0.015em] flex-1 text-center">AI辅导-M-260105</h2>
<button class="text-text-main flex size-10 shrink-0 items-center justify-center rounded-full shadow-neu-flat-sm active:shadow-neu-pressed transition-all bg-page-bg hover:text-primary">
<span class="material-symbols-outlined text-xl">history</span>
</button>
</div>
<div class="flex-1 overflow-y-auto w-full p-5 space-y-8 bg-page-bg scroll-smooth pb-4" id="chat-container">
<div class="mx-auto max-w-sm w-full bg-page-bg p-4 rounded-2xl shadow-neu-flat mb-8 transform transition-transform hover:scale-[1.01] duration-300">
<div class="flex items-center gap-4">
<div class="flex-1 min-w-0">
<div class="flex justify-between items-center mb-1">
<span class="text-[11px] font-bold uppercase tracking-wider text-primary">Calculus</span>
<span class="text-[11px] text-text-muted">Q1</span>
</div>
<p class="text-sm font-medium truncate text-text-main">Find the derivative of f(x) = 3x²...</p>
</div>
<button class="shrink-0 text-gray-400 hover:text-primary transition-colors">
<span class="material-symbols-outlined text-2xl">expand_more</span>
</button>
</div>
</div>
<div class="flex justify-center">
<p class="text-[11px] text-red-500 font-medium bg-page-bg px-4 py-1.5 rounded-full shadow-neu-flat">Today 14:30</p>
</div>
<div class="flex items-end gap-3 group">
<div class="bg-center bg-no-repeat aspect-square bg-cover rounded-full w-10 h-10 shrink-0 shadow-neu-flat border-2 border-page-bg" data-alt="AI Robot Avatar" style='background-image: url("https://lh3.googleusercontent.com/aida-public/AB6AXuAKQMAG4ca5kJE6ng_0wSQyRkrMtkzD6BzuLWG6S9J4ALLjWZ-9pwRhRz-6Tg2wboVK-YkGs9lZkIOHbUAs0t8194lohOwOuWlYw_LPiGnygwAycT1AMFKQe3kJc7_rdmE2JgRqPuXdg5Euo-ZXK23OYrbZ0oERXNTnMxsaasCRlRdL78_Xu53hP45UGU3f2Au-2r6WCEZvwyN2y-ev-HdpgWBUsj_5mxG1A3wIF8FnTWqWln2p4pJXZlbJ6LamdiyhAHFcGGMFlGY");'></div>
<div class="flex flex-1 flex-col gap-1 items-start max-w-[85%]">
<p class="text-text-muted text-[11px] font-medium ml-2">AI Tutor</p>
<div class="text-[15px] font-light leading-relaxed rounded-2xl rounded-bl-none px-5 py-4 bg-page-bg text-text-main shadow-bubble-ai border border-white/40">
<p class="text-gray-700">I see you're stuck on this calculus problem. Let's break it down. First, let's identify the derivative rule we need. Since we have a term with an exponent, we'll use the Power Rule.</p>
</div>
</div>
</div>
<div class="flex items-end gap-3 justify-end group">
<div class="flex flex-1 flex-col gap-1 items-end max-w-[85%]">
<div class="text-[15px] font-light leading-relaxed rounded-2xl rounded-br-none px-5 py-4 bg-page-bg text-text-main shadow-bubble-user">
<p>I don't remember the Power Rule perfectly. Why did the exponent change to negative?</p>
</div>
<p class="text-text-muted text-[10px] font-medium mr-2">Read 14:32</p>
</div>
<div class="flex items-center justify-center w-10 h-10 shrink-0 rounded-full bg-page-bg text-gray-400 shadow-neu-flat">
<span class="material-symbols-outlined text-xl">person</span>
</div>
</div>
<div class="flex items-end gap-3 group">
<div class="bg-center bg-no-repeat aspect-square bg-cover rounded-full w-10 h-10 shrink-0 shadow-neu-flat border-2 border-page-bg" data-alt="AI Robot Avatar" style='background-image: url("https://lh3.googleusercontent.com/aida-public/AB6AXuBDZLsVDvt3T5m_aju8ZvoWfJxOgGCozzzw_rJM2iekAycsMTS4xNqkG-NKm063ZzZHlKwSyx31EhtLKolEO1mRDzkkdiQxqSFZ70rYHvvp3x0_HjnQbW_aY96nowQRZ7pp2Z6rMn1z3S-I8nHlbMgx3wlcPC5GBMuuUhRHCZfSCNfJkvofqlpA77cA271eWDoqybrmIG_z9v-VzOE2GjP_J63amDsZW97aGrZrTrZrUcGGPb4YTMr5DlMI33ahdTarRDyhzlwtREU");'></div>
<div class="flex flex-1 flex-col gap-1 items-start max-w-[90%]">
<p class="text-text-muted text-[11px] font-medium ml-2">AI Tutor</p>
<div class="text-[15px] font-light leading-relaxed rounded-2xl rounded-bl-none px-5 py-4 bg-page-bg text-text-main shadow-bubble-ai border border-white/40 w-full">
<p class="mb-3 text-gray-700">Great question. When we move <span class="font-math italic text-primary font-medium">x²</span> from the denominator to the numerator, the exponent becomes negative.</p>
<div class="my-4 p-4 bg-math-bg-light rounded-xl shadow-neu-pressed">
<p class="font-math text-center whitespace-nowrap text-text-main text-lg">
<span class="italic text-gray-500">f(x)</span> = 
                            <span class="inline-flex flex-col align-middle text-center mx-2">
<span class="border-b border-gray-400 pb-0.5 mb-0.5 text-gray-800">1</span>
<span class="text-gray-800">x²</span>
</span>
                            = <span class="italic text-primary font-semibold">x</span>⁻²
                        </p>
</div>
<p class="text-gray-700">Does that make sense? We can now apply the rule <span class="font-math bg-page-bg px-2 py-0.5 rounded italic text-primary font-medium shadow-neu-flat-sm">nxⁿ⁻¹</span>.</p>
</div>
</div>
</div>
<div class="flex items-end gap-3">
<div class="bg-center bg-no-repeat aspect-square bg-cover rounded-full w-10 h-10 shrink-0 opacity-50 grayscale shadow-none" data-alt="AI Robot Avatar" style='background-image: url("https://lh3.googleusercontent.com/aida-public/AB6AXuDXPNP5ZnTqKd_lojLbsQc0dFK0VAnqcdH_D0JMExWBEKOSlFd4OrOoXRsWOH3UCD2w9w-w46dxpHOa09Oy58oTiW4F5NW9SgwYfLj69lNAFCWvJrNjSpiZ9P-EMKGvZTIgrhSK1HgtIj6WbgxuJn0CEjol657jEqrOW0CNDJir02vkOaQ_BwNG316ZVBFwcdHWGppF2F3pAVU8exuArSIoRDoI-iG-a0T-9uB9iJ54nFzZucEUW3xDTjs9dwnNZjHy17e3XatbsRM");'></div>
<div class="bg-page-bg px-5 py-4 rounded-2xl rounded-bl-none flex items-center gap-1.5 shadow-bubble-ai border border-white/40 h-[52px]">
<div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0ms"></div>
<div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 150ms"></div>
<div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 300ms"></div>
</div>
</div>
<div class="h-6"></div>
</div>
<div class="w-full bg-page-bg shrink-0 z-20 pb-8 pt-2">
<div class="flex gap-3 p-4 overflow-x-auto no-scrollbar mask-gradient">
<button class="flex h-9 shrink-0 items-center justify-center gap-x-2 rounded-xl bg-page-bg pl-4 pr-5 transition-all shadow-neu-flat active:shadow-neu-pressed hover:text-primary">
<span class="material-symbols-outlined text-primary text-[20px]">lightbulb</span>
<p class="text-text-main text-xs font-semibold whitespace-nowrap">Show similar example</p>
</button>
<button class="flex h-9 shrink-0 items-center justify-center gap-x-2 rounded-xl bg-page-bg pl-4 pr-5 transition-all shadow-neu-flat active:shadow-neu-pressed hover:text-primary">
<span class="material-symbols-outlined text-green-600 text-[20px]">check_circle</span>
<p class="text-text-main text-xs font-semibold whitespace-nowrap">I understand now</p>
</button>
<button class="flex h-9 shrink-0 items-center justify-center gap-x-2 rounded-xl bg-page-bg pl-4 pr-5 transition-all shadow-neu-flat active:shadow-neu-pressed hover:text-primary">
<span class="material-symbols-outlined text-red-500 text-[20px]">help</span>
<p class="text-text-main text-xs font-semibold whitespace-nowrap">Explain step 2</p>
</button>
</div>
<div class="px-4 flex items-end gap-3">
<div class="flex-1 bg-page-bg rounded-[1.5rem] shadow-input-inner transition-all flex items-center min-h-[52px] border border-transparent focus-within:border-primary/10">
<input class="w-full bg-transparent border-none focus:ring-0 text-sm px-5 py-3 placeholder-gray-400 text-text-main leading-relaxed" placeholder="Ask a follow-up question..." type="text"/>
<button class="p-3 mr-1 text-gray-400 hover:text-primary transition-colors">
<span class="material-symbols-outlined text-[22px]">mic</span>
</button>
</div>
<button class="size-12 rounded-full bg-page-bg text-accent-yellow shadow-bubble-send hover:scale-[1.02] active:scale-95 active:shadow-neu-pressed transition-all shrink-0 flex items-center justify-center border border-white/50">
<span class="material-symbols-outlined text-[24px] ml-0.5 text-accent-yellow">send</span>
</button>
</div>
</div>

</body></html>

# 数据档案
## 错题面板
##<!DOCTYPE html>
<html class="light" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Data Archive Page</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&amp;display=swap" rel="stylesheet"/>
<script id="tailwind-config">
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        "primary": "#363c4a",
                        "background-light": "#EFEEEE",
                        "background-dark": "#17181b",
                        "surface-raised": "#EFEEEE",
                        "text-primary": "#363C4A",
                        "shadow-dark": "#C9CBD0", 
                        "shadow-light": "#FFFFFF",
                        "accent-blue": "#26A9DB",
                        "accent-orange": "#F5891A",
                    },
                    fontFamily: {
                        "display": ["Manrope", "sans-serif"]
                    },
                    boxShadow: {
                        'neumorphic-raised': '-8px -8px 20px #FFFFFF, 8px 8px 20px #C9CBD0',
                        'neumorphic-pressed': 'inset 6px 6px 12px #C9CBD0, inset -6px -6px 12px #FFFFFF',
                        'neumorphic-pressed-sm': 'inset 3px 3px 6px #C9CBD0, inset -3px -3px 6px #FFFFFF',
                        'neumorphic-tag': 'inset 2px 2px 5px #D1D3D6, inset -2px -2px 5px #FFFFFF',
                        'switch-glow': '0 0 15px rgba(38, 169, 219, 0.2), -4px -4px 10px #FFFFFF, 4px 4px 10px #C9CBD0',
                    },
                    borderRadius: {
                        "DEFAULT": "0.5rem",
                        "lg": "1rem",
                        "xl": "1.5rem",
                        "2xl": "2rem",
                        "3xl": "3rem",
                        "full": "9999px"
                    },
                },
            },
        }
    </script>
<style>
        body {
            background-color: #EFEEEE;
            font-family: 'Manrope', sans-serif;
            color: #363C4A;
        }.no-scrollbar::-webkit-scrollbar {
            display: none;
        }
        .no-scrollbar {
            -ms-overflow-style: none;
            scrollbar-width: none;
        }
        body {
            min-height: max(884px, 100dvh);
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-background-light min-h-screen relative flex flex-col overflow-x-hidden antialiased selection:bg-accent-blue/20">
<header class="pt-6 pb-2 px-6 flex items-center justify-between z-10 sticky top-0 bg-[#EFEEEE]/90 backdrop-blur-sm">
<div class="size-12"></div>
<h1 class="text-xl font-extrabold tracking-tight text-text-primary">DATA ARCHIVE</h1>
<button class="flex items-center justify-center size-12 rounded-full shadow-neumorphic-raised active:shadow-neumorphic-pressed transition-all duration-200 text-text-primary">
<span class="material-symbols-outlined text-[24px]">search</span>
</button>
</header>
<main class="flex-1 flex flex-col px-6 pb-32">
<div class="mt-8 mb-10 w-full flex justify-center">
<div class="relative w-full max-w-[340px] h-16 rounded-full shadow-neumorphic-pressed bg-[#EFEEEE] p-1.5 flex items-center">
<div class="absolute left-1.5 h-12 w-[calc(50%-6px)] bg-[#EFEEEE] rounded-full shadow-switch-glow z-10 transition-transform duration-300 ease-out transform translate-x-0"></div>
<button class="w-1/2 h-full rounded-full z-20 flex items-center justify-center text-sm font-bold tracking-wider text-text-primary transition-colors">
                    MATHEMATICS
                </button>
<button class="w-1/2 h-full rounded-full z-20 flex items-center justify-center text-sm font-bold tracking-wider text-text-primary/40 hover:text-text-primary/70 transition-colors">
                    ENGLISH
                </button>
</div>
</div>
<div class="grid grid-cols-2 gap-5 w-full">
<div class="group relative flex flex-col p-5 bg-[#EFEEEE] rounded-3xl shadow-neumorphic-raised active:shadow-neumorphic-pressed transition-all duration-200 cursor-pointer overflow-hidden border border-white/50">
<div class="flex justify-between items-start mb-4">
<div class="size-10 rounded-full shadow-neumorphic-pressed-sm flex items-center justify-center text-text-primary/80">
<span class="material-symbols-outlined text-[20px]">function</span>
</div>
<span class="text-4xl font-extrabold text-text-primary leading-none tracking-tight">128</span>
</div>
<h3 class="text-lg font-bold text-black mb-6 mt-1">Algebra</h3>
<div class="flex flex-wrap gap-2 mt-auto">
<span class="px-3 py-1.5 rounded-full bg-[#EFEEEE] shadow-neumorphic-tag text-[10px] font-semibold text-text-primary/70 tracking-wide uppercase">Equations</span>
<span class="px-3 py-1.5 rounded-full bg-[#EFEEEE] shadow-neumorphic-tag text-[10px] font-semibold text-text-primary/70 tracking-wide uppercase">Polynomials</span>
</div>
</div>
<div class="group relative flex flex-col p-5 bg-[#EFEEEE] rounded-3xl shadow-neumorphic-raised active:shadow-neumorphic-pressed transition-all duration-200 cursor-pointer overflow-hidden border border-white/50">
<div class="flex justify-between items-start mb-4">
<div class="size-10 rounded-full shadow-neumorphic-pressed-sm flex items-center justify-center text-text-primary/80">
<span class="material-symbols-outlined text-[20px]">change_history</span>
</div>
<span class="text-4xl font-extrabold text-text-primary leading-none tracking-tight">42</span>
</div>
<h3 class="text-lg font-bold text-black mb-6 mt-1">Geometry</h3>
<div class="flex flex-wrap gap-2 mt-auto">
<span class="px-3 py-1.5 rounded-full bg-[#EFEEEE] shadow-neumorphic-tag text-[10px] font-semibold text-text-primary/70 tracking-wide uppercase">Triangles</span>
<span class="px-3 py-1.5 rounded-full bg-[#EFEEEE] shadow-neumorphic-tag text-[10px] font-semibold text-text-primary/70 tracking-wide uppercase">Circles</span>
</div>
</div>
<div class="group relative flex flex-col p-5 bg-[#EFEEEE] rounded-3xl shadow-neumorphic-raised active:shadow-neumorphic-pressed transition-all duration-200 cursor-pointer overflow-hidden border border-white/50">
<div class="flex justify-between items-start mb-4">
<div class="size-10 rounded-full shadow-neumorphic-pressed-sm flex items-center justify-center text-text-primary/80">
<span class="material-symbols-outlined text-[20px]">show_chart</span>
</div>
<span class="text-4xl font-extrabold text-text-primary leading-none tracking-tight">86</span>
</div>
<h3 class="text-lg font-bold text-black mb-6 mt-1">Calculus</h3>
<div class="flex flex-wrap gap-2 mt-auto">
<span class="px-3 py-1.5 rounded-full bg-[#EFEEEE] shadow-neumorphic-tag text-[10px] font-semibold text-text-primary/70 tracking-wide uppercase">Limits</span>
<span class="px-3 py-1.5 rounded-full bg-[#EFEEEE] shadow-neumorphic-tag text-[10px] font-semibold text-text-primary/70 tracking-wide uppercase">Derivatives</span>
</div>
</div>
<div class="group relative flex flex-col p-5 bg-[#EFEEEE] rounded-3xl shadow-neumorphic-raised active:shadow-neumorphic-pressed transition-all duration-200 cursor-pointer overflow-hidden border border-white/50">
<div class="flex justify-between items-start mb-4">
<div class="size-10 rounded-full shadow-neumorphic-pressed-sm flex items-center justify-center text-text-primary/80">
<span class="material-symbols-outlined text-[20px]">bar_chart_4_bars</span>
</div>
<span class="text-4xl font-extrabold text-text-primary leading-none tracking-tight">15</span>
</div>
<h3 class="text-lg font-bold text-black mb-6 mt-1">Statistics</h3>
<div class="flex flex-wrap gap-2 mt-auto">
<span class="px-3 py-1.5 rounded-full bg-[#EFEEEE] shadow-neumorphic-tag text-[10px] font-semibold text-text-primary/70 tracking-wide uppercase">Mean</span>
<span class="px-3 py-1.5 rounded-full bg-[#EFEEEE] shadow-neumorphic-tag text-[10px] font-semibold text-text-primary/70 tracking-wide uppercase">Median</span>
</div>
</div>
<div class="group relative flex flex-col p-5 bg-[#EFEEEE] rounded-3xl shadow-neumorphic-raised active:shadow-neumorphic-pressed transition-all duration-200 cursor-pointer overflow-hidden border border-white/50">
<div class="flex justify-between items-start mb-4">
<div class="size-10 rounded-full shadow-neumorphic-pressed-sm flex items-center justify-center text-text-primary/80">
<span class="material-symbols-outlined text-[20px]">casino</span>
</div>
<span class="text-4xl font-extrabold text-text-primary leading-none tracking-tight">09</span>
</div>
<h3 class="text-lg font-bold text-black mb-6 mt-1">Probability</h3>
<div class="flex flex-wrap gap-2 mt-auto">
<span class="px-3 py-1.5 rounded-full bg-[#EFEEEE] shadow-neumorphic-tag text-[10px] font-semibold text-text-primary/70 tracking-wide uppercase">Events</span>
<span class="px-3 py-1.5 rounded-full bg-[#EFEEEE] shadow-neumorphic-tag text-[10px] font-semibold text-text-primary/70 tracking-wide uppercase">Logic</span>
</div>
</div>
<div class="group relative flex flex-col p-5 bg-[#EFEEEE] rounded-3xl shadow-neumorphic-pressed transition-all duration-200 cursor-pointer overflow-hidden opacity-60">
<div class="flex justify-between items-start mb-4">
<div class="size-10 rounded-full shadow-neumorphic-raised flex items-center justify-center text-text-primary/40">
<span class="material-symbols-outlined text-[20px]">lock</span>
</div>
<span class="text-4xl font-extrabold text-text-primary/40 leading-none tracking-tight">00</span>
</div>
<h3 class="text-lg font-bold text-text-primary/50 mb-6 mt-1">Logic</h3>
<div class="flex flex-wrap gap-2 mt-auto">
<span class="px-3 py-1.5 rounded-full bg-[#EFEEEE] border border-white/20 text-[10px] font-semibold text-text-primary/40 tracking-wide uppercase">Locked</span>
</div>
</div>
</div>
</main>
<div class="fixed bottom-0 w-full px-6 pb-8 pt-4 z-50 pointer-events-none flex justify-center bg-gradient-to-t from-[#EFEEEE] via-[#EFEEEE]/80 to-transparent">
<button class="absolute left-12 bottom-10 pointer-events-auto size-16 rounded-full bg-[#EFEEEE] shadow-neumorphic-raised active:shadow-neumorphic-pressed flex items-center justify-center text-text-primary/60 hover:text-text-primary transition-all border-4 border-[#EFEEEE] group">
<span class="font-extrabold text-lg group-active:scale-95 transition-transform tracking-wider">OK</span>
</button>
<button class="pointer-events-auto size-20 rounded-full bg-[#EFEEEE] shadow-neumorphic-raised active:shadow-neumorphic-pressed flex items-center justify-center text-text-primary/60 hover:text-text-primary transition-all border-4 border-[#EFEEEE] relative group">
<span class="material-symbols-outlined text-[36px] group-active:scale-95 transition-transform">home</span>
</button>
</div>
</body></html>

## 已掌握面板
跟错题面板类似，唯一的区别是显示的数据不同，在这个界面的左下角，OK按钮显示被按下的拟态。

## 分类面板
这个面板是在错题面板或已掌握面板，点击分类显示的数据后进入的页面
<!DOCTYPE html>
<html class="light" lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>错题检视流</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@200;300;400;500;600;700;800&amp;family=Noto+Sans+SC:wght@100;300;400;500;700;900&amp;family=Noto+Serif+SC:wght@500;600;700&amp;display=swap" rel="stylesheet"/>
<script id="tailwind-config">
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        "primary": "#363c4a",
                        "background-light": "#EFEEEE",
                        "text-primary": "#363C4A",
                        "text-secondary": "#9AA5B6",
                        "accent-blue": "#26A9DB",
                        "accent-green": "#4ADE80",
                    },
                    fontFamily: {
                        "sans": ["Manrope", "Noto Sans SC", "sans-serif"],
                        "serif": ["Noto Serif SC", "serif"],
                    },
                    boxShadow: {
                        'neumorphic-raised': '-8px -8px 20px #FFFFFF, 8px 8px 20px #CFCFCF',
                        'neumorphic-raised-sm': '-4px -4px 10px #FFFFFF, 4px 4px 10px #CFCFCF',
                        'neumorphic-pressed': 'inset 6px 6px 12px #CFCFCF, inset -6px -6px 12px #FFFFFF',
                        'neumorphic-pressed-sm': 'inset 3px 3px 6px #CFCFCF, inset -3px -3px 6px #FFFFFF',
                        'neumorphic-pressed-deep': 'inset 10px 10px 20px #CFCFCF, inset -10px -10px 20px #FFFFFF',
                        'glow-blue': 'inset 3px 3px 6px #CFCFCF, inset -3px -3px 6px #FFFFFF, 0 0 15px rgba(38, 169, 219, 0.25)',
                        'glow-green': 'inset 3px 3px 6px #CFCFCF, inset -3px -3px 6px #FFFFFF, 0 0 15px rgba(74, 222, 128, 0.4)',
                        'neumorphic-inset-xs': 'inset 2px 2px 4px #CFCFCF, inset -2px -2px 4px #FFFFFF',
                    },
                    borderRadius: {
                        "3xl": "1.75rem",
                    }
                },
            },
        }
    </script>
<style>
        body {
            background-color: #EFEEEE;
            color: #363C4A;
        }
        .hide-scrollbar::-webkit-scrollbar {
            display: none;
        }
        .hide-scrollbar {
            -ms-overflow-style: none;
            scrollbar-width: none;
        }
        body {
          min-height: max(884px, 100dvh);
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-background-light min-h-screen relative flex flex-col antialiased">
<header class="pt-8 pb-4 px-6 flex flex-col z-20 sticky top-0 bg-[#EFEEEE]/95 backdrop-blur-md transition-all">
<div class="flex items-center justify-between mb-6">
<button class="flex items-center justify-center size-12 rounded-full shadow-neumorphic-raised active:shadow-neumorphic-pressed transition-all duration-200 text-text-primary group">
<span class="material-symbols-outlined text-[32px] group-active:scale-90 transition-transform">chevron_left</span>
</button>
<h1 class="text-xl font-bold tracking-tight text-text-primary flex-1 text-center pr-12">代数</h1>
</div>
<div class="w-full py-2">
<div class="grid grid-cols-3 gap-3 p-1.5 rounded-full bg-[#EFEEEE] shadow-neumorphic-pressed w-full">
<button class="w-full py-2 rounded-full bg-[#EFEEEE] shadow-neumorphic-raised text-text-primary font-bold text-sm tracking-wide transition-all duration-300">
                    全部
                </button>
<button class="w-full py-2 rounded-full text-text-secondary font-semibold text-sm tracking-wide transition-all duration-300 hover:text-text-primary">
                    待复习
                </button>
<button class="w-full py-2 rounded-full text-text-secondary font-semibold text-sm tracking-wide transition-all duration-300 hover:text-text-primary">
                    已掌握
                </button>
</div>
</div>
</header>
<main class="flex-1 flex flex-col items-center gap-8 px-4 pb-40 w-full max-w-lg mx-auto">
<div class="w-[90%] flex flex-col p-5 bg-[#EFEEEE] rounded-[2rem] shadow-neumorphic-raised transition-all duration-300">
<div class="w-full aspect-[4/3] rounded-2xl bg-[#EFEEEE] shadow-neumorphic-pressed-deep p-6 mb-5 relative overflow-hidden flex flex-col justify-center">
<div class="font-serif text-primary text-lg leading-loose">
                    已知函数 <span class="font-bold italic font-sans">f(x)</span> = <span class="italic font-sans">x</span>² - 2<span class="italic font-sans">x</span> + <span class="italic font-sans">c</span>，若 <span class="font-bold italic font-sans">f(x)</span> 在区间 [0, 3] 上的最小值为 1，求 <span class="italic font-sans">c</span> 的值。
                </div>
</div>
<div class="flex items-center justify-between pl-2">
<div class="flex flex-col justify-center gap-2">
<div class="self-start text-[10px] text-text-secondary font-medium tracking-widest opacity-80 font-sans">2023.11.05</div>
<div class="flex gap-2">
<span class="text-[10px] text-text-secondary px-3 py-1.5 rounded-lg bg-[#EFEEEE] shadow-neumorphic-inset-xs font-medium">函数</span>
<span class="text-[10px] text-text-secondary px-3 py-1.5 rounded-lg bg-[#EFEEEE] shadow-neumorphic-inset-xs font-medium">最值</span>
</div>
</div>
<button class="size-16 rounded-full bg-[#EFEEEE] shadow-neumorphic-raised active:shadow-neumorphic-pressed flex items-center justify-center text-text-secondary transition-all duration-300 group hover:text-accent-blue font-black text-xl tracking-wider">
                    OK
                </button>
</div>
</div>
<div class="w-[90%] flex flex-col p-5 bg-[#EFEEEE] rounded-[2rem] shadow-neumorphic-raised transition-all duration-300">
<div class="w-full aspect-[4/3] rounded-2xl bg-[#EFEEEE] shadow-neumorphic-pressed-deep p-6 mb-5 relative overflow-hidden flex flex-col justify-center">
<div class="font-serif text-primary text-lg leading-loose opacity-60">
                    求不等式组 <br/>
<span class="italic font-sans">x</span> - 3(x - 2) ≥ 4 <br/>
                    的非负整数解。
                </div>
</div>
<div class="flex items-center justify-between pl-2">
<div class="flex flex-col justify-center gap-2">
<div class="self-start text-[10px] text-text-secondary font-medium tracking-widest opacity-80 font-sans">2023.11.03</div>
<div class="flex gap-2">
<span class="text-[10px] text-text-secondary px-3 py-1.5 rounded-lg bg-[#EFEEEE] shadow-neumorphic-inset-xs font-medium">不等式</span>
</div>
</div>
<button class="size-16 rounded-full bg-[#EFEEEE] shadow-glow-green flex items-center justify-center text-accent-green transition-all duration-300 font-black text-xl tracking-wider">
                    OK
                </button>
</div>
</div>
<div class="w-[90%] flex flex-col p-5 bg-[#EFEEEE] rounded-[2rem] shadow-neumorphic-raised transition-all duration-300">
<div class="w-full aspect-[4/3] rounded-2xl bg-[#EFEEEE] shadow-neumorphic-pressed-deep p-6 mb-5 relative overflow-hidden flex flex-col justify-center">
<div class="font-serif text-primary text-lg leading-loose">
                    如图，在 Rt△<span class="italic font-sans">ABC</span> 中，∠<span class="italic font-sans">C</span> = 90°，<span class="italic font-sans">AD</span> 平分 ∠<span class="italic font-sans">BAC</span> 交 <span class="italic font-sans">BC</span> 于 <span class="italic font-sans">D</span>，若 <span class="italic font-sans">BC</span> = 32，且 <span class="italic font-sans">BD</span> : <span class="italic font-sans">CD</span> = 9 : 7，求 <span class="italic font-sans">D</span> 到 <span class="italic font-sans">AB</span> 的距离。
                </div>
</div>
<div class="flex items-center justify-between pl-2">
<div class="flex flex-col justify-center gap-2">
<div class="self-start text-[10px] text-text-secondary font-medium tracking-widest opacity-80 font-sans">2023.10.29</div>
<div class="flex gap-2">
<span class="text-[10px] text-text-secondary px-3 py-1.5 rounded-lg bg-[#EFEEEE] shadow-neumorphic-inset-xs font-medium">几何</span>
<span class="text-[10px] text-text-secondary px-3 py-1.5 rounded-lg bg-[#EFEEEE] shadow-neumorphic-inset-xs font-medium">角平分线</span>
</div>
</div>
<button class="size-16 rounded-full bg-[#EFEEEE] shadow-neumorphic-raised active:shadow-neumorphic-pressed flex items-center justify-center text-text-secondary transition-all duration-300 group hover:text-accent-blue font-black text-xl tracking-wider">
                    OK
                </button>
</div>
</div>
</main>
<div class="fixed bottom-0 left-0 w-full pb-8 pt-12 z-50 pointer-events-none flex justify-center bg-gradient-to-t from-[#EFEEEE] via-[#EFEEEE]/90 to-transparent">
<button class="pointer-events-auto size-20 rounded-full bg-[#EFEEEE] shadow-neumorphic-raised active:shadow-neumorphic-pressed flex items-center justify-center text-text-secondary hover:text-text-primary transition-all border-[3px] border-[#EFEEEE] relative group">
<span class="material-symbols-outlined text-[32px] group-active:scale-95 transition-transform">home</span>
</button>
</div>

</body></html>

# 分析
## 分析页面
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Analysis Page - Minimalist Knob Console</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&amp;family=Nunito:wght@400;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script>
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        primary: "#FF4B4B", // Red accent for pointers
                        "background-light": "#EFEEEE", // Unified Background as requested
                        "background-dark": "#292D32",
                        "text-main-light": "#475569",
                        "text-main-dark": "#E2E8F0",
                        "text-sub-light": "#94A3B8",
                        "text-sub-dark": "#64748B",
                    },
                    fontFamily: {
                        display: ["Montserrat", "sans-serif"],
                        body: ["Nunito", "sans-serif"],
                    },
                    boxShadow: {
                        // Tuned for #EFEEEE - Clean Neumorphism
                        'neu-flat': '8px 8px 16px #cbcfcf, -8px -8px 16px #ffffff',
                        'neu-pressed': 'inset 6px 6px 12px #cbcfcf, inset -6px -6px 12px #ffffff',
                        'neu-knob': '12px 12px 24px #cbcfcf, -12px -12px 24px #ffffff', // Floating effect
                        'neu-nav': '5px 5px 10px #cbcfcf, -5px -5px 10px #ffffff',
                        // Dark Mode
                        'neu-flat-dark': '6px 6px 12px #1c1f24, -6px -6px 12px #363b40',
                        'neu-pressed-dark': 'inset 4px 4px 8px #1c1f24, inset -4px -4px 8px #363b40',
                        'neu-knob-dark': '8px 8px 16px #1c1f24, -8px -8px 16px #363b40',
                        'neu-nav-dark': '4px 4px 8px #1c1f24, -4px -4px 8px #363b40',
                    },
                    borderRadius: {
                        DEFAULT: "1rem",
                    },
                },
            },
        };
    </script>
<style>
        body {
            transition: background-color 0.3s ease, color 0.3s ease;
        }
        .knob-marker {
            position: absolute;
            left: 50%;
            top: 50%;
            transform-origin: center;
        }
        .knob-inner {background: linear-gradient(145deg, #ffffff, #f2f4f6);
        }
        .dark .knob-inner {
            background: linear-gradient(145deg, #2c3035, #25282c);
        }.pointer-line {
            left: 50%;
            transform: translateX(-50%);
        }
    </style>
<style>
        body {
          min-height: max(884px, 100dvh);
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-background-light dark:bg-background-dark min-h-screen font-body antialiased selection:bg-primary selection:text-white overflow-hidden">
<div class="relative w-full h-screen bg-background-light dark:bg-background-dark flex flex-col justify-between p-6">
<div class="absolute inset-0 pointer-events-none opacity-50 bg-gradient-to-br from-white/60 to-transparent dark:from-white/5 dark:to-transparent"></div>
<div class="absolute top-0 left-0 w-64 h-64 bg-white opacity-40 dark:opacity-5 rounded-full filter blur-[100px] pointer-events-none -translate-x-1/2 -translate-y-1/2"></div>
<div class="mt-12 text-center relative z-10">
<h1 class="text-sm tracking-[0.2em] font-bold text-text-main-light dark:text-text-main-dark font-display uppercase opacity-80">
            Analysis
        </h1>
</div>
<div class="flex-1 flex flex-col justify-center items-center space-y-20 relative z-10">
<div class="w-full grid grid-cols-2 gap-8 px-2">
<div class="flex flex-col items-center">
<div class="relative w-36 h-36 rounded-full shadow-neu-knob dark:shadow-neu-knob-dark flex items-center justify-center bg-background-light dark:bg-background-dark">
<div class="absolute inset-0 rounded-full border border-white/50 dark:border-white/5 opacity-60"></div>
<div class="w-24 h-24 rounded-full knob-inner shadow-[0_2px_8px_rgba(0,0,0,0.05)] flex items-center justify-center relative transform transition-transform duration-500 rotate-0">
<div class="absolute top-2 w-1 h-3 bg-primary rounded-full shadow-[0_0_6px_rgba(255,75,75,0.5)] pointer-line"></div>
<div class="w-3 h-3 rounded-full bg-background-light dark:bg-background-dark shadow-neu-pressed dark:shadow-neu-pressed-dark"></div>
</div>
<div class="absolute -top-10 text-[11px] font-bold text-primary tracking-widest">THIS WEEK</div>
<div class="absolute -bottom-10 text-[10px] font-semibold text-text-sub-light dark:text-text-sub-dark tracking-widest opacity-60">MONTH</div>
<div class="absolute -left-10 text-[10px] font-semibold text-text-sub-light dark:text-text-sub-dark tracking-widest transform -rotate-90 opacity-60">CUSTOM</div>
</div>
</div>
<div class="flex flex-col items-center">
<div class="relative w-36 h-36 rounded-full shadow-neu-knob dark:shadow-neu-knob-dark flex items-center justify-center bg-background-light dark:bg-background-dark">
<div class="absolute inset-0 rounded-full border border-white/50 dark:border-white/5 opacity-60"></div>
<div class="w-24 h-24 rounded-full knob-inner shadow-[0_2px_8px_rgba(0,0,0,0.05)] flex items-center justify-center relative transform transition-transform duration-500 rotate-0">
<div class="absolute top-2 w-1 h-3 bg-primary rounded-full shadow-[0_0_6px_rgba(255,75,75,0.5)] pointer-line"></div>
<div class="w-3 h-3 rounded-full bg-background-light dark:bg-background-dark shadow-neu-pressed dark:shadow-neu-pressed-dark"></div>
</div>
<div class="absolute -top-10 text-[11px] font-bold text-primary tracking-widest">MATH</div>
<div class="absolute -right-12 top-1/2 transform -translate-y-1/2 text-[10px] font-semibold text-text-sub-light dark:text-text-sub-dark tracking-widest rotate-90 opacity-60">ENGLISH</div>
</div>
</div>
</div>
<div class="pt-4">
<button class="group w-24 h-24 rounded-full bg-background-light dark:bg-background-dark shadow-neu-knob dark:shadow-neu-knob-dark active:shadow-neu-pressed dark:active:shadow-neu-pressed-dark flex items-center justify-center transition-all duration-200 outline-none focus:outline-none">
<div class="w-20 h-20 rounded-full flex items-center justify-center border border-white/40 dark:border-white/5 bg-gradient-to-br from-white/40 to-transparent dark:from-white/5">
<span class="text-xs font-bold text-text-main-light dark:text-text-main-dark tracking-[0.2em] group-active:scale-95 transition-transform ml-1">START</span>
</div>
</button>
</div>
</div>
<div class="mb-8 w-full grid grid-cols-3 items-center relative z-10">
<div class="flex justify-center">
<button class="w-14 h-14 rounded-full bg-background-light dark:bg-background-dark shadow-neu-nav dark:shadow-neu-nav-dark active:shadow-neu-pressed dark:active:shadow-neu-pressed-dark flex items-center justify-center text-text-sub-light dark:text-text-sub-dark hover:text-primary transition-colors duration-200">
<span class="material-symbols-outlined" style="font-size: 24px;">description</span>
</button>
</div>
<div class="flex justify-center">
<button class="w-16 h-16 rounded-full bg-background-light dark:bg-background-dark shadow-neu-nav dark:shadow-neu-nav-dark active:shadow-neu-pressed dark:active:shadow-neu-pressed-dark flex items-center justify-center text-text-main-light dark:text-text-main-dark hover:text-primary transition-colors duration-200 -mt-2 border border-white/40 dark:border-white/5">
<span class="material-symbols-outlined" style="font-size: 30px;">home</span>
</button>
</div>
<div class="flex justify-center"></div>
</div>
</div>

</body></html>

## 报告详情页
<!DOCTYPE html>
<html class="light" lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>学情报告详情 - Noteacher</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;family=Noto+Sans+SC:wght@400;500;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script id="tailwind-config">
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        "neu-bg": "#EFEEEE",
                        "neu-accent-blue": "#3B82F6",
                        "neu-accent-yellow": "#FBBF24",
                        "neu-accent-purple": "#A855F7",
                        "neu-accent-green": "#10B981",
                        "neu-accent-red": "#EF4444",
                        "neu-text-dark": "#1A202C",
                        "neu-text": "#4A5568",
                        "neu-text-light": "#A0AEC0",
                    },
                    boxShadow: {
                        'neu-convex': '6px 6px 12px #c9cbd0, -6px -6px 12px #ffffff',
                        'neu-convex-lg': '12px 12px 24px #c9cbd0, -12px -12px 24px #ffffff',
                        'neu-convex-sm': '4px 4px 8px #c9cbd0, -4px -4px 8px #ffffff',
                        'neu-inset': 'inset 6px 6px 12px #c9cbd0, inset -6px -6px 12px #ffffff',
                        'neu-inset-lg': 'inset 12px 12px 24px #c9cbd0, inset -12px -12px 24px #ffffff',
                        'neu-inset-sm': 'inset 3px 3px 6px #c9cbd0, inset -3px -3px 6px #ffffff',
                        'neu-convex-deep': '8px 8px 16px #c9cbd0, -8px -8px 16px #ffffff',
                    }
                },
            },
        }
    </script>
<style type="text/tailwindcss">
        body {
            background-color: #EFEEEE;
            font-family: 'Lexend', 'Noto Sans SC', sans-serif;
            color: #4A5568;
        }
        .material-symbols-outlined {
            font-variation-settings: 'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24;
            vertical-align: middle;
        }
        .section-title {
            @apply flex items-center gap-1 text-sm font-bold text-neu-text-dark mb-4;
        }
        .section-title .info-icon {
            @apply text-neu-text-light text-[14px];
        }
    </style>
<style>
        body {
            min-height: max(884px, 100dvh);
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="antialiased select-none">
<div class="relative flex min-h-screen w-full flex-col max-w-md mx-auto bg-neu-bg pb-32 px-6 overflow-x-hidden">
<header class="flex items-center justify-between pt-12 pb-8 sticky top-0 bg-neu-bg/80 backdrop-blur-sm z-30">
<button class="w-10 h-10 rounded-full bg-neu-bg shadow-neu-convex flex items-center justify-center active:shadow-neu-inset transition-all duration-200">
<span class="material-symbols-outlined text-neu-text-dark text-lg">chevron_left</span>
</button>
<h1 class="text-lg font-bold tracking-wider text-neu-text-dark">AI评测报告</h1>
<div class="w-10"></div>
</header>
<main class="space-y-12">
<section class="flex flex-col items-center">
<div class="w-64 h-64 rounded-full bg-neu-bg shadow-neu-inset-lg flex flex-col items-center justify-center relative mb-10">
<div class="text-[52px] font-bold text-neu-text-dark leading-none">85%</div>
<div class="text-xs font-bold text-neu-accent-red mt-2 tracking-widest">正确率</div>
</div>
<div class="flex w-full items-center justify-center px-4">
<div class="flex-1 flex flex-col items-center justify-center py-2">
<span class="text-2xl font-bold text-neu-text-dark">50</span>
<span class="text-[11px] text-neu-text-light font-bold mt-1">正确</span>
</div>
<div class="w-[1px] h-8 bg-black/5 mx-2"></div>
<div class="flex-1 flex flex-col items-center justify-center py-2">
<span class="text-2xl font-bold text-neu-text-dark">12</span>
<span class="text-[11px] text-neu-text-light font-bold mt-1">错误</span>
</div>
<div class="w-[1px] h-8 bg-black/5 mx-2"></div>
<div class="flex-1 flex flex-col items-center justify-center py-2">
<span class="text-2xl font-bold text-neu-text-dark">1</span>
<span class="text-[11px] text-neu-text-light font-bold mt-1">待定</span>
</div>
</div>
</section>
<section>
<div class="section-title">
                薄弱知识点 TOP 3
                <span class="material-symbols-outlined info-icon">info</span>
</div>
<div class="grid grid-cols-3 gap-4">
<div class="aspect-square bg-neu-bg shadow-neu-convex rounded-2xl flex flex-col items-center justify-center p-3 text-center">
<span class="text-[11px] font-bold text-neu-text-dark mb-4 leading-tight">数列求和</span>
<span class="text-2xl font-bold text-neu-text-dark">10</span>
</div>
<div class="aspect-square bg-neu-bg shadow-neu-convex rounded-2xl flex flex-col items-center justify-center p-3 text-center">
<span class="text-[11px] font-bold text-neu-text-dark mb-4 leading-tight">导数应用</span>
<span class="text-2xl font-bold text-neu-text-dark">8</span>
</div>
<div class="aspect-square bg-neu-bg shadow-neu-convex rounded-2xl flex flex-col items-center justify-center p-3 text-center">
<span class="text-[11px] font-bold text-neu-text-dark mb-4 leading-tight">向量运算</span>
<span class="text-2xl font-bold text-neu-text-dark">6</span>
</div>
</div>
</section>
<section>
<div class="section-title">
                错因统计
                <span class="material-symbols-outlined info-icon">info</span>
</div>
<div class="bg-neu-bg shadow-neu-convex rounded-[32px] p-8 pb-10 flex h-64 border border-white/40 relative">
<div class="absolute left-6 top-8 bottom-16 flex flex-col justify-between text-[9px] text-neu-accent-red font-bold h-[calc(100%-6rem)]">
<span>100</span>
<span>75</span>
<span>50</span>
<span>25</span>
<span>0</span>
</div>
<div class="flex justify-between items-end h-full w-full pl-8">
<div class="flex flex-col items-center gap-4 h-full justify-end">
<div class="w-10 h-[35%] rounded-full shadow-neu-convex bg-neu-bg relative flex items-end">
</div>
<span class="text-[10px] font-bold text-neu-text-light whitespace-nowrap -rotate-45 mb-1">计算失误</span>
</div>
<div class="flex flex-col items-center gap-4 h-full justify-end">
<div class="w-10 h-[75%] rounded-full shadow-neu-convex bg-neu-accent-red relative flex items-end">
</div>
<span class="text-[10px] font-bold text-neu-text-light whitespace-nowrap -rotate-45 mb-1">概念不清</span>
</div>
<div class="flex flex-col items-center gap-4 h-full justify-end">
<div class="w-10 h-[25%] rounded-full shadow-neu-convex bg-neu-bg relative flex items-end">
</div>
<span class="text-[10px] font-bold text-neu-text-light whitespace-nowrap -rotate-45 mb-1">审题不慎</span>
</div>
<div class="flex flex-col items-center gap-4 h-full justify-end">
<div class="w-10 h-[65%] rounded-full shadow-neu-convex bg-neu-bg relative flex items-end">
</div>
<span class="text-[10px] font-bold text-neu-text-light whitespace-nowrap -rotate-45 mb-1">公式遗忘</span>
</div>
</div>
</div>
</section>
<section>
<div class="section-title">
                错题趋势
                <span class="material-symbols-outlined info-icon">info</span>
</div>
<div class="grid grid-cols-2 gap-4">
<div class="h-32 bg-neu-bg shadow-neu-inset rounded-2xl p-4 flex flex-col justify-between overflow-hidden relative">
<span class="text-[10px] font-bold text-neu-text-light uppercase tracking-tighter">知识点</span>
<svg class="absolute bottom-4 left-0 w-full h-16" preserveAspectRatio="none" viewBox="0 0 100 40">
<pattern height="10" id="dots" patternUnits="userSpaceOnUse" width="10">
<circle cx="2" cy="2" fill="#D1D5DB" r="1"></circle>
</pattern>
<rect fill="url(#dots)" height="40" opacity="0.5" width="100"></rect>
<path d="M0 35 Q 25 5 50 25 T 100 10" fill="none" stroke="#FBBF24" stroke-linecap="round" stroke-width="3"></path>
<path d="M0 25 Q 20 15 50 35 T 100 15" fill="none" opacity="0.6" stroke="#3B82F6" stroke-linecap="round" stroke-width="3"></path>
</svg>
</div>
<div class="h-32 bg-neu-bg shadow-neu-inset rounded-2xl p-4 flex flex-col justify-between overflow-hidden relative">
<span class="text-[10px] font-bold text-neu-text-light uppercase tracking-tighter">正确趋势</span>
<svg class="absolute bottom-4 left-0 w-full h-16" preserveAspectRatio="none" viewBox="0 0 100 40">
<rect fill="url(#dots)" height="40" opacity="0.5" width="100"></rect>
<path d="M0 35 Q 25 5 50 25 T 100 10" fill="none" stroke="#A855F7" stroke-linecap="round" stroke-width="3"></path>
<path d="M0 25 Q 20 15 50 35 T 100 15" fill="none" opacity="0.6" stroke="#FBBF24" stroke-linecap="round" stroke-width="3"></path>
</svg>
</div>
</div>
</section>
<section class="pb-16">
<div class="section-title">
                AI 评价与建议
            </div>
<div class="w-full bg-neu-bg shadow-neu-inset-lg rounded-[32px] p-8 border border-white/20">
<p class="text-sm leading-relaxed text-neu-text-dark font-medium italic mb-6">
                    “根据本次诊断，你在‘几何证明’板块存在明显的逻辑断层。建议优先回顾第4章的辅助线添加技巧。当前整体正确率呈上升趋势，继续保持。”
                </p>
</div>
</section>
</main>
<footer class="fixed bottom-0 left-0 right-0 h-28 flex items-center justify-center pointer-events-none z-40">
<div class="max-w-md w-full flex justify-center pb-8">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-convex-deep flex items-center justify-center pointer-events-auto active:shadow-neu-inset transition-all duration-300 border border-white/30">
<span class="material-symbols-outlined text-neu-text-light" style="font-size: 32px;">home</span>
</button>
</div>
</footer>
</div>
</body></html>

## 报告记录列表
<!DOCTYPE html>
<html class="light" lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>分析报告记录 - Noteacher</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script id="tailwind-config">
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        "primary": "#3B82F6", // Tech blue
                        "accent": "#FCD34D", // Bright yellow
                        "neu-bg": "#EFEEEE", // NEW: Standard warm gray-white background
                        "neu-text": "#374151", // Deep blue-gray
                        "neu-text-secondary": "#9CA3AF", // Mid gray
                        "crimson-red": "#DC143C", // Crimson red for text
                        "rating-a": "#10B981",
                        "rating-b": "#F59E0B",
                        "rating-c": "#EF4444",
                    },
                    fontFamily: {
                        "display": ["Lexend", "Noto Sans", "sans-serif"]
                    },
                    boxShadow: {
                        // Adjusted shadows for #EFEEEE background (Warm/Neutral Gray Shadows)
                        'neu-base': '12px 12px 24px #d1d0d0, -12px -12px 24px #ffffff',
                        'neu-flat': '6px 6px 12px #d1d0d0, -6px -6px 12px #ffffff',
                        'neu-pressed': 'inset 4px 4px 8px #d1d0d0, inset -4px -4px 8px #ffffff',
                        'neu-icon-btn': '5px 5px 10px #d1d0d0, -5px -5px 10px #ffffff',
                        'neu-timeline-line': 'inset 2px 2px 4px #d1d0d0, inset -2px -2px 4px #ffffff',
                    }
                },
            },
        }
    </script>
<style>
        .material-symbols-outlined {
            font-variation-settings: 'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24;
        }
        body {
             background-color: #EFEEEE;
             min-height: 100vh;
             font-family: 'Lexend', sans-serif;
        }
        .no-scrollbar::-webkit-scrollbar {
            display: none;
        }
        .no-scrollbar {
            -ms-overflow-style: none;
            scrollbar-width: none;
        }
        .timeline-connector {
            position: absolute;
            left: 20px;
            top: 20px;
            bottom: -20px;
            width: 4px;
            background: #EFEEEE;
            border-radius: 99px;box-shadow: inset 1px 1px 2px #d1d0d0, inset -1px -1px 2px #ffffff;
            z-index: 0;
        }
        .timeline-dot {box-shadow: 3px 3px 6px #d1d0d0, -3px -3px 6px #ffffff;
            z-index: 10;
        }
    </style>
<style>
        body {
            min-height: max(884px, 100dvh);
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-neu-bg text-neu-text transition-colors duration-200 antialiased overflow-hidden">
<div class="relative flex h-full min-h-screen w-full flex-col max-w-md mx-auto bg-neu-bg pb-24">
<header class="sticky top-0 z-30 flex items-center justify-center px-6 pt-12 pb-6 bg-neu-bg/90 backdrop-blur-sm relative">
<button class="absolute left-6 w-10 h-10 rounded-full bg-neu-bg shadow-neu-icon-btn flex items-center justify-center text-neu-text-secondary hover:text-primary active:shadow-neu-pressed transition-all duration-300">
<span class="material-symbols-outlined text-[24px]">chevron_left</span>
</button>
<h1 class="text-xl font-bold text-neu-text-secondary tracking-tight">报告记录</h1>
</header>
<main class="flex-1 px-6 overflow-y-auto no-scrollbar pb-10">
<div class="relative mb-8">
<div class="timeline-connector"></div>
<div class="pl-12 space-y-5">
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-4 flex items-center justify-between gap-3 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-3">
<h3 class="font-bold text-neu-text text-sm">数学学情报告</h3>
<div class="flex items-center gap-2 text-[10px] text-crimson-red mt-1 font-medium">
<span>#R260107</span>
<span class="w-1 h-1 rounded-full bg-crimson-red/50"></span>
<span>2026.01.07</span>
</div>
</div>
<div class="flex flex-col items-center justify-center shrink-0">
<div class="h-10 w-10 rounded-full bg-neu-bg shadow-neu-pressed flex items-center justify-center text-neu-text-secondary group-hover:text-primary transition-colors">
<span class="material-symbols-outlined text-[20px]">visibility</span>
</div>
</div>
</div>
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-4 flex items-center justify-between gap-3 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-3">
<h3 class="font-bold text-neu-text text-sm">英语学情报告</h3>
<div class="flex items-center gap-2 text-[10px] text-crimson-red mt-1 font-medium">
<span>#R260107</span>
<span class="w-1 h-1 rounded-full bg-crimson-red/50"></span>
<span>2026.01.07</span>
</div>
</div>
<div class="flex flex-col items-center justify-center shrink-0">
<div class="h-10 w-10 rounded-full bg-neu-bg shadow-neu-pressed flex items-center justify-center text-neu-text-secondary group-hover:text-primary transition-colors">
<span class="material-symbols-outlined text-[20px]">visibility</span>
</div>
</div>
</div>
</div>
</div>
<div class="relative mb-8">
<div class="timeline-connector"></div>
<div class="pl-12 space-y-5">
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-4 flex items-center justify-between gap-3 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-3">
<h3 class="font-bold text-neu-text text-sm">物理学情报告</h3>
<div class="flex items-center gap-2 text-[10px] text-crimson-red mt-1 font-medium">
<span>#R260106</span>
<span class="w-1 h-1 rounded-full bg-crimson-red/50"></span>
<span>2026.01.06</span>
</div>
</div>
<div class="flex flex-col items-center justify-center shrink-0">
<div class="h-10 w-10 rounded-full bg-neu-bg shadow-neu-pressed flex items-center justify-center text-neu-text-secondary group-hover:text-primary transition-colors">
<span class="material-symbols-outlined text-[20px]">visibility</span>
</div>
</div>
</div>
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-4 flex items-center justify-between gap-3 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-3">
<h3 class="font-bold text-neu-text text-sm">数学学情报告</h3>
<div class="flex items-center gap-2 text-[10px] text-crimson-red mt-1 font-medium">
<span>#R260106</span>
<span class="w-1 h-1 rounded-full bg-crimson-red/50"></span>
<span>2026.01.06</span>
</div>
</div>
<div class="flex flex-col items-center justify-center shrink-0">
<div class="h-10 w-10 rounded-full bg-neu-bg shadow-neu-pressed flex items-center justify-center text-neu-text-secondary group-hover:text-primary transition-colors">
<span class="material-symbols-outlined text-[20px]">visibility</span>
</div>
</div>
</div>
</div>
</div>
</main>
<div class="fixed bottom-8 left-0 right-0 flex justify-center z-40 pointer-events-none">
<div class="pointer-events-auto flex flex-col items-center gap-2">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-flat flex items-center justify-center text-neu-text-secondary hover:text-primary active:shadow-neu-pressed transition-all duration-300 group">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform">home</span>
</button>
<span class="text-[10px] font-bold tracking-widest text-neu-text-secondary uppercase">HOME</span>
</div>
</div>
</div>

</body></html>

# 批改历史记录
## 批改历史记录
<!DOCTYPE html>
<html class="light" lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>历史记录 - Flow State</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script id="tailwind-config">
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        "primary": "#3B82F6", // Tech blue
                        "accent": "#FCD34D", // Bright yellow
                        "neu-bg": "#EFEEEE", // Updated per request: Standard gray-white
                        "neu-text": "#1F2937", // Deep black/gray
                        "neu-text-secondary": "#9CA3AF", // Mid gray
                        "rating-a": "#10B981",
                        "rating-b": "#F59E0B",
                        "rating-c": "#EF4444",
                    },
                    fontFamily: {
                        "display": ["Lexend", "Noto Sans", "sans-serif"]
                    },
                    boxShadow: {
                        // Adjusted shadows for #EFEEEE background
                        'neu-base': '12px 12px 24px #cbd0d6, -12px -12px 24px #ffffff',
                        'neu-flat': '6px 6px 12px #c8cdd6, -6px -6px 12px #ffffff',
                        'neu-pressed': 'inset 4px 4px 8px #c8cdd6, inset -4px -4px 8px #ffffff',
                        'neu-icon-btn': '5px 5px 10px #c8cdd6, -5px -5px 10px #ffffff',
                        'neu-timeline-line': 'inset 2px 2px 4px #c8cdd6, inset -2px -2px 4px #ffffff',
                    }
                },
            },
        }
    </script>
<style>
        .material-symbols-outlined {
            font-variation-settings: 'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24;
        }
        body {
             background-color: #EFEEEE;
             min-height: 100vh;
             font-family: 'Lexend', sans-serif;
        }
        .no-scrollbar::-webkit-scrollbar {
            display: none;
        }
        .no-scrollbar {
            -ms-overflow-style: none;
            scrollbar-width: none;
        }.timeline-connector {
            position: absolute;
            left: 20px;
            top: 40px;
            bottom: -20px;
            width: 4px;
            background: #EFEEEE;
            border-radius: 99px;
            box-shadow: inset 1px 1px 2px #c8cdd6, inset -1px -1px 2px #ffffff;
            z-index: 0;
        }
        .timeline-dot {
            box-shadow: 3px 3px 6px #c8cdd6, -3px -3px 6px #ffffff;
            z-index: 10;
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-neu-bg text-neu-text transition-colors duration-200 antialiased overflow-hidden">
<div class="relative flex h-full min-h-screen w-full flex-col max-w-md mx-auto bg-neu-bg pb-24">
<header class="sticky top-0 z-30 flex items-center justify-between px-6 pt-12 pb-6 bg-neu-bg/90 backdrop-blur-sm relative">
<div class="w-10"></div> 
<h1 class="text-xl font-bold text-neu-text-secondary tracking-tight text-center">历史记录</h1>
<button class="h-10 w-10 rounded-full flex items-center justify-center shadow-neu-icon-btn active:shadow-neu-pressed transition-all duration-300 bg-neu-bg">
<span class="material-symbols-outlined text-neu-text-secondary" style="font-size: 20px;">tune</span>
</button>
</header>
<main class="flex-1 px-6 overflow-y-auto no-scrollbar pb-10">
<div class="relative mb-8">
<div class="timeline-connector"></div>
<div class="flex items-center mb-6 relative z-10">
<div class="w-10 flex justify-center">
<div class="h-4 w-4 rounded-full bg-neu-bg border-2 border-primary timeline-dot"></div>
</div>
<h2 class="ml-2 text-sm font-bold text-neu-text-secondary uppercase tracking-widest">今天 10月24日</h2>
</div>
<div class="pl-12 space-y-5">
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-5 flex items-center justify-between gap-4 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex items-center gap-4 flex-1">
<div class="h-12 w-12 flex items-center justify-center text-neu-text-secondary shrink-0">
<span class="material-symbols-outlined">calculate</span>
</div>
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-3">
<h3 class="font-bold text-neu-text text-base">数学</h3>
<div class="flex items-center gap-2 text-xs text-neu-text-secondary mt-1">
<span>#84021</span>
<span class="w-1 h-1 rounded-full bg-neu-text-secondary"></span>
<span>14:30</span>
</div>
</div>
</div>
<div class="flex flex-col items-end gap-1 shrink-0">
<div class="h-8 w-8 rounded-lg bg-neu-bg shadow-neu-pressed flex items-center justify-center">
<span class="text-sm font-bold text-rating-a">A+</span>
</div>
</div>
</div>
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-5 flex items-center justify-between gap-4 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex items-center gap-4 flex-1">
<div class="h-12 w-12 flex items-center justify-center text-neu-text-secondary shrink-0">
<span class="material-symbols-outlined">menu_book</span>
</div>
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-3">
<h3 class="font-bold text-neu-text text-base">英语</h3>
<div class="flex items-center gap-2 text-xs text-neu-text-secondary mt-1">
<span>#84019</span>
<span class="w-1 h-1 rounded-full bg-neu-text-secondary"></span>
<span>10:15</span>
</div>
</div>
</div>
<div class="flex flex-col items-end gap-1 shrink-0">
<div class="h-8 w-8 rounded-lg bg-neu-bg shadow-neu-pressed flex items-center justify-center">
<span class="text-sm font-bold text-rating-b">B</span>
</div>
</div>
</div>
</div>
</div>
<div class="relative mb-8">
<div class="timeline-connector"></div>
<div class="flex items-center mb-6 relative z-10">
<div class="w-10 flex justify-center">
<div class="h-4 w-4 rounded-full bg-neu-bg border-2 border-neu-text-secondary timeline-dot"></div>
</div>
<h2 class="ml-2 text-sm font-bold text-neu-text-secondary uppercase tracking-widest">昨天 10月23日</h2>
</div>
<div class="pl-12 space-y-5">
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-5 flex items-center justify-between gap-4 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex items-center gap-4 flex-1">
<div class="h-12 w-12 flex items-center justify-center text-neu-text-secondary shrink-0">
<span class="material-symbols-outlined">science</span>
</div>
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-3">
<h3 class="font-bold text-neu-text text-base">物理</h3>
<div class="flex items-center gap-2 text-xs text-neu-text-secondary mt-1">
<span>#83942</span>
<span class="w-1 h-1 rounded-full bg-neu-text-secondary"></span>
<span>16:45</span>
</div>
</div>
</div>
<div class="flex flex-col items-end gap-1 shrink-0">
<div class="h-8 w-8 rounded-lg bg-neu-bg shadow-neu-pressed flex items-center justify-center">
<span class="text-sm font-bold text-rating-a">A</span>
</div>
</div>
</div>
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-5 flex items-center justify-between gap-4 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex items-center gap-4 flex-1">
<div class="h-12 w-12 flex items-center justify-center text-neu-text-secondary shrink-0">
<span class="material-symbols-outlined">calculate</span>
</div>
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-3">
<h3 class="font-bold text-neu-text text-base">数学</h3>
<div class="flex items-center gap-2 text-xs text-neu-text-secondary mt-1">
<span>#83911</span>
<span class="w-1 h-1 rounded-full bg-neu-text-secondary"></span>
<span>09:20</span>
</div>
</div>
</div>
<div class="flex flex-col items-end gap-1 shrink-0">
<div class="h-8 w-8 rounded-lg bg-neu-bg shadow-neu-pressed flex items-center justify-center">
<span class="text-sm font-bold text-rating-c">C</span>
</div>
</div>
</div>
</div>
</div>
</main>
<div class="fixed bottom-8 left-0 right-0 flex justify-center z-40 pointer-events-none">
<div class="pointer-events-auto flex flex-col items-center gap-2">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-flat flex items-center justify-center text-neu-text-secondary hover:text-primary active:shadow-neu-pressed transition-all duration-300 group">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform">home</span>
</button>
<span class="text-[10px] font-bold tracking-widest text-neu-text-secondary uppercase">首页</span>
</div>
</div>
</div>

</body></html>

## 历史筛选弹窗
<!DOCTYPE html>
<html class="light" lang="zh-CN"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>历史记录 - Flow State</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script id="tailwind-config">
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        "primary": "#3B82F6", // Tech blue
                        "accent": "#FCD34D", // Bright yellow
                        "neu-bg": "#EFEEEE", // Updated: Unified Standard Gray-White
                        "neu-popup": "#EFEEEE", // Updated: Unified Standard Gray-White
                        "neu-text": "#1F2937", // Deep black/gray
                        "neu-text-secondary": "#9CA3AF", // Mid gray
                        "rating-a": "#10B981",
                        "rating-b": "#F59E0B",
                        "rating-c": "#EF4444",
                    },
                    fontFamily: {
                        "display": ["Lexend", "Noto Sans", "sans-serif"]
                    },
                    boxShadow: {
                        // Optimizing shadows for #EFEEEE background
                        // Using a neutral cool grey #cbd0d6 for shadow to maintain clean look
                        'neu-base': '12px 12px 24px #cbd0d6, -12px -12px 24px #ffffff',
                        'neu-flat': '6px 6px 12px #cbd0d6, -6px -6px 12px #ffffff',
                        'neu-flat-sm': '3px 3px 6px #cbd0d6, -3px -3px 6px #ffffff',
                        'neu-pressed': 'inset 4px 4px 8px #cbd0d6, inset -4px -4px 8px #ffffff',
                        'neu-pressed-deep': 'inset 6px 6px 12px #cbd0d6, inset -6px -6px 12px #ffffff',
                        'neu-icon-btn': '5px 5px 10px #cbd0d6, -5px -5px 10px #ffffff',
                        'neu-timeline-line': 'inset 2px 2px 4px #cbd0d6, inset -2px -2px 4px #ffffff',
                        'glow-blue': '0 0 15px rgba(59, 130, 246, 0.3)',
                        // Refined Popup specific shadows for "delicate 3D feel" on #EFEEEE
                        'popup-base': '20px 20px 40px #cbd0d6, -20px -20px 40px #ffffff',
                        'popup-flat': '5px 5px 10px #cbd0d6, -5px -5px 10px #ffffff',
                        'popup-flat-sm': '3px 3px 6px #cbd0d6, -3px -3px 6px #ffffff',
                        'popup-pressed': 'inset 4px 4px 8px #cbd0d6, inset -4px -4px 8px #ffffff',
                        'popup-pressed-deep': 'inset 5px 5px 10px #bdc2c9, inset -5px -5px 10px #ffffff', // Slightly deeper for selected state
                    }
                },
            },
        }
    </script>
<style>
        .material-symbols-outlined {
            font-variation-settings: 'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24;
        }
        body {
             background-color: #EFEEEE;
             min-height: 100vh;
             font-family: 'Lexend', sans-serif;
        }
        .no-scrollbar::-webkit-scrollbar {
            display: none;
        }
        .no-scrollbar {
            -ms-overflow-style: none;
            scrollbar-width: none;
        }.timeline-connector {
            position: absolute;
            left: 20px;
            top: 40px;
            bottom: -20px;
            width: 4px;
            background: #EFEEEE;
            border-radius: 99px;
            box-shadow: inset 1px 1px 2px #cbd0d6, inset -1px -1px 2px #ffffff;
            z-index: 0;
        }
        .timeline-dot {
            box-shadow: 3px 3px 6px #cbd0d6, -3px -3px 6px #ffffff;
            z-index: 10;
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="bg-neu-bg text-neu-text transition-colors duration-200 antialiased overflow-hidden">
<div class="relative flex h-full min-h-screen w-full flex-col max-w-md mx-auto bg-neu-bg pb-24">
<header class="sticky top-0 z-30 flex items-center justify-center px-6 pt-12 pb-6 bg-neu-bg/90 relative">
<h1 class="text-xl font-bold text-neu-text-secondary tracking-tight">历史记录</h1>
<button class="absolute right-6 h-10 w-10 rounded-full flex items-center justify-center shadow-neu-icon-btn active:shadow-neu-pressed transition-all duration-300 bg-neu-bg z-40">
<span class="material-symbols-outlined text-neu-text-secondary" style="font-size: 20px;">tune</span>
</button>
</header>
<main class="flex-1 px-6 overflow-y-auto no-scrollbar pb-10">
<div class="relative mb-8">
<div class="timeline-connector"></div>
<div class="flex items-center mb-6 relative z-10">
<div class="w-10 flex justify-center">
<div class="h-4 w-4 rounded-full bg-neu-bg border-2 border-primary timeline-dot"></div>
</div>
<h2 class="ml-2 text-sm font-bold text-neu-text-secondary uppercase tracking-widest">今天 10月24日</h2>
</div>
<div class="pl-12 space-y-5">
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-5 flex items-center justify-between gap-4 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex items-center gap-4 flex-1">
<div class="h-12 w-12 rounded-full flex items-center justify-center text-neu-text-secondary shrink-0">
<span class="material-symbols-outlined">calculate</span>
</div>
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-2">
<h3 class="font-bold text-neu-text text-base">数学</h3>
<div class="flex items-center gap-2 text-xs text-neu-text-secondary mt-1">
<span>#84021</span>
<span class="w-1 h-1 rounded-full bg-neu-text-secondary"></span>
<span>14:30</span>
</div>
</div>
</div>
<div class="flex flex-col items-end gap-1 shrink-0">
<div class="h-8 w-8 rounded-full bg-neu-bg shadow-neu-pressed flex items-center justify-center">
<span class="text-sm font-bold text-rating-a">A+</span>
</div>
</div>
</div>
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-5 flex items-center justify-between gap-4 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex items-center gap-4 flex-1">
<div class="h-12 w-12 rounded-full flex items-center justify-center text-neu-text-secondary shrink-0">
<span class="material-symbols-outlined">menu_book</span>
</div>
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-2">
<h3 class="font-bold text-neu-text text-base">英语</h3>
<div class="flex items-center gap-2 text-xs text-neu-text-secondary mt-1">
<span>#84019</span>
<span class="w-1 h-1 rounded-full bg-neu-text-secondary"></span>
<span>10:15</span>
</div>
</div>
</div>
<div class="flex flex-col items-end gap-1 shrink-0">
<div class="h-8 w-8 rounded-full bg-neu-bg shadow-neu-pressed flex items-center justify-center">
<span class="text-sm font-bold text-rating-b">B</span>
</div>
</div>
</div>
</div>
</div>
<div class="relative mb-8">
<div class="timeline-connector"></div>
<div class="flex items-center mb-6 relative z-10">
<div class="w-10 flex justify-center">
<div class="h-4 w-4 rounded-full bg-neu-bg border-2 border-neu-text-secondary timeline-dot"></div>
</div>
<h2 class="ml-2 text-sm font-bold text-neu-text-secondary uppercase tracking-widest">昨天 10月23日</h2>
</div>
<div class="pl-12 space-y-5">
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-5 flex items-center justify-between gap-4 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex items-center gap-4 flex-1">
<div class="h-12 w-12 rounded-full flex items-center justify-center text-neu-text-secondary shrink-0">
<span class="material-symbols-outlined">science</span>
</div>
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-2">
<h3 class="font-bold text-neu-text text-base">物理</h3>
<div class="flex items-center gap-2 text-xs text-neu-text-secondary mt-1">
<span>#83942</span>
<span class="w-1 h-1 rounded-full bg-neu-text-secondary"></span>
<span>16:45</span>
</div>
</div>
</div>
<div class="flex flex-col items-end gap-1 shrink-0">
<div class="h-8 w-8 rounded-full bg-neu-bg shadow-neu-pressed flex items-center justify-center">
<span class="text-sm font-bold text-rating-a">A</span>
</div>
</div>
</div>
<div class="relative group rounded-2xl bg-neu-bg shadow-neu-flat p-5 flex items-center justify-between gap-4 active:scale-[0.98] transition-transform duration-200 cursor-pointer">
<div class="flex items-center gap-4 flex-1">
<div class="h-12 w-12 rounded-full flex items-center justify-center text-neu-text-secondary shrink-0">
<span class="material-symbols-outlined">calculate</span>
</div>
<div class="flex-1 bg-neu-bg shadow-neu-pressed rounded-xl px-4 py-2">
<h3 class="font-bold text-neu-text text-base">数学</h3>
<div class="flex items-center gap-2 text-xs text-neu-text-secondary mt-1">
<span>#83911</span>
<span class="w-1 h-1 rounded-full bg-neu-text-secondary"></span>
<span>09:20</span>
</div>
</div>
</div>
<div class="flex flex-col items-end gap-1 shrink-0">
<div class="h-8 w-8 rounded-full bg-neu-bg shadow-neu-pressed flex items-center justify-center">
<span class="text-sm font-bold text-rating-c">C</span>
</div>
</div>
</div>
</div>
</div>
</main>
<div class="fixed bottom-8 left-0 right-0 flex justify-center z-30 pointer-events-none">
<div class="pointer-events-auto flex flex-col items-center gap-2">
<button class="w-16 h-16 rounded-full bg-neu-bg shadow-neu-flat flex items-center justify-center text-neu-text-secondary hover:text-primary active:shadow-neu-pressed transition-all duration-300 group">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform">home</span>
</button>
<span class="text-[10px] font-bold tracking-widest text-neu-text-secondary uppercase">首页</span>
</div>
</div>
<div class="fixed inset-0 z-50 flex items-center justify-center px-4">
<div class="absolute inset-0 bg-neu-bg/60 backdrop-blur-[6px]"></div>
<div class="relative w-full max-w-[340px] bg-neu-popup rounded-[40px] shadow-popup-base pt-20 px-6 pb-6 flex flex-col gap-8 animate-in fade-in zoom-in-95 duration-300">
<button class="absolute top-5 left-6 w-10 h-10 rounded-full bg-neu-popup shadow-popup-flat flex items-center justify-center text-neu-text-secondary active:shadow-popup-pressed transition-all duration-200 z-50">
<span class="material-symbols-outlined font-bold text-lg">close</span>
</button>
<div class="relative w-full h-16 bg-neu-popup rounded-full shadow-popup-pressed p-1.5 flex items-center select-none cursor-pointer">
<div class="absolute left-1.5 top-1.5 bottom-1.5 w-[calc(50%-6px)] bg-neu-popup rounded-full shadow-[5px_5px_10px_#cbd0d6,-5px_-5px_10px_#ffffff] shadow-glow-blue flex items-center justify-center z-10 transition-transform duration-300">
<span class="text-neu-text font-bold text-lg tracking-wide">数学</span>
</div>
<div class="w-1/2 h-full flex items-center justify-center z-0">
</div>
<div class="w-1/2 h-full flex items-center justify-center z-0">
<span class="text-neu-text-secondary font-medium text-lg tracking-wide">英语</span>
</div>
</div>
<div class="flex flex-col gap-5 select-none">
<div class="flex items-center justify-between px-2">
<button class="w-10 h-10 rounded-full bg-neu-popup shadow-popup-flat flex items-center justify-center text-neu-text-secondary active:shadow-popup-pressed transition-all duration-200">
<span class="material-symbols-outlined text-sm font-bold">arrow_back_ios_new</span>
</button>
<div class="text-neu-text font-bold text-lg tracking-widest">2024年 10月</div>
<button class="w-10 h-10 rounded-full bg-neu-popup shadow-popup-flat flex items-center justify-center text-neu-text-secondary active:shadow-popup-pressed transition-all duration-200">
<span class="material-symbols-outlined text-sm font-bold">arrow_forward_ios</span>
</button>
</div>
<div class="grid grid-cols-7 gap-y-4 gap-x-2 text-center">
<div class="text-neu-text-secondary text-[10px] font-medium pb-2">日</div>
<div class="text-neu-text-secondary text-[10px] font-medium pb-2">一</div>
<div class="text-neu-text-secondary text-[10px] font-medium pb-2">二</div>
<div class="text-neu-text-secondary text-[10px] font-medium pb-2">三</div>
<div class="text-neu-text-secondary text-[10px] font-medium pb-2">四</div>
<div class="text-neu-text-secondary text-[10px] font-medium pb-2">五</div>
<div class="text-neu-text-secondary text-[10px] font-medium pb-2">六</div>
<div class="h-9 w-9"></div>
<div class="h-9 w-9"></div>
<div class="group h-9 w-9 mx-auto flex items-center justify-center rounded-full bg-neu-popup shadow-popup-flat-sm text-neu-text-secondary text-xs active:shadow-popup-pressed cursor-pointer transition-all">20</div>
<div class="group h-9 w-9 mx-auto flex items-center justify-center rounded-full bg-neu-popup shadow-popup-flat-sm text-neu-text-secondary text-xs active:shadow-popup-pressed cursor-pointer transition-all">21</div>
<div class="group h-9 w-9 mx-auto flex items-center justify-center rounded-full bg-neu-popup shadow-popup-flat-sm text-neu-text-secondary text-xs active:shadow-popup-pressed cursor-pointer transition-all">22</div>
<div class="group h-9 w-9 mx-auto flex items-center justify-center rounded-full bg-neu-popup shadow-popup-flat-sm text-neu-text-secondary text-xs active:shadow-popup-pressed cursor-pointer transition-all">23</div>
<div class="h-10 w-10 -my-0.5 mx-auto flex items-center justify-center rounded-full bg-neu-popup shadow-popup-pressed-deep cursor-pointer relative">
<span class="text-[#E11D48] font-bold text-base drop-shadow-[0_0_5px_rgba(225,29,72,0.6)]">24</span>
</div>
<div class="group h-9 w-9 mx-auto flex items-center justify-center rounded-full bg-neu-popup shadow-popup-flat-sm text-neu-text-secondary text-xs active:shadow-popup-pressed cursor-pointer transition-all">25</div>
<div class="group h-9 w-9 mx-auto flex items-center justify-center rounded-full bg-neu-popup shadow-popup-flat-sm text-neu-text-secondary text-xs active:shadow-popup-pressed cursor-pointer transition-all">26</div>
<div class="group h-9 w-9 mx-auto flex items-center justify-center rounded-full bg-neu-popup shadow-popup-flat-sm text-neu-text-secondary text-xs active:shadow-popup-pressed cursor-pointer transition-all">27</div>
<div class="group h-9 w-9 mx-auto flex items-center justify-center rounded-full bg-neu-popup shadow-popup-flat-sm text-neu-text-secondary text-xs active:shadow-popup-pressed cursor-pointer transition-all">28</div>
<div class="group h-9 w-9 mx-auto flex items-center justify-center rounded-full bg-neu-popup shadow-popup-flat-sm text-neu-text-secondary text-xs active:shadow-popup-pressed cursor-pointer transition-all">29</div>
<div class="group h-9 w-9 mx-auto flex items-center justify-center rounded-full bg-neu-popup shadow-popup-flat-sm text-neu-text-secondary text-xs active:shadow-popup-pressed cursor-pointer transition-all">30</div>
</div>
</div>
<button class="w-full h-14 rounded-2xl bg-neu-popup shadow-popup-flat flex items-center justify-center gap-2 text-[#1F2937] active:shadow-popup-pressed transition-all active:scale-[0.98] group">
<span class="font-bold text-lg tracking-wider group-active:translate-y-px">确认</span>
</button>
</div>
</div>
</div>
</body></html>

# 我的
## 我的
<!DOCTYPE html>
<html class="light" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>My Profile - Minimalist Neumorphism</title>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script>
    tailwind.config = {
        darkMode: "class",
        theme: {
            extend: {
                colors: {
                    "primary": "#3B82F6", 
                    "background-light": "#EFEEEE", 
                    "text-dark": "#2D3748",
                    "text-gray": "#718096",
                },
                fontFamily: {
                    "display": ["Lexend", "sans-serif"]
                },
                boxShadow: {
                    'neu-flat': '8px 8px 16px #d1d1d1, -8px -8px 16px #ffffff',
                    'neu-pressed': 'inset 6px 6px 12px #d1d1d1, inset -6px -6px 12px #ffffff',
                    'neu-icon': '5px 5px 10px #d1d1d1, -5px -5px 10px #ffffff',
                    'neu-btn': '4px 4px 8px #b1c9f8, -4px -4px 8px #ffffff', 
                    'neu-home': '6px 6px 12px #d1d1d1, -6px -6px 12px #ffffff',
                }
            },
        },
    }
</script>
<style>
    body {
        min-height: max(884px, 100dvh);
        background-color: #EFEEEE;
    }
    .neu-flat {
        background: #EFEEEE;
        box-shadow: 9px 9px 18px #d1d1d1, -9px -9px 18px #ffffff;
        border: 1px solid rgba(255,255,255,0.4);
    }
    .neu-pressed {
        background: #EFEEEE;
        box-shadow: inset 5px 5px 10px #d1d1d1, inset -5px -5px 10px #ffffff;
    }
    .neu-btn-long {
        background: #EFEEEE;
        box-shadow: 6px 6px 12px #d1d1d1, -6px -6px 12px #ffffff;
        border-radius: 1rem;
        transition: all 0.2s ease;
        border: 1px solid rgba(255,255,255,0.4);
    }
    .neu-btn-long:active {
        box-shadow: inset 3px 3px 6px #d1d1d1, inset -3px -3px 6px #ffffff;
        transform: scale(0.99);
    }
    .neu-nav {
        background: #EFEEEE;
        box-shadow: 0 -4px 20px rgba(163,177,198,0.2);
    }
    .home-indicator {
        width: 134px;
        height: 5px;
        background-color: #CBD5E0;
        border-radius: 100px;
        margin: 0 auto;
        box-shadow: inset 1px 1px 2px #b8c0ca, inset -1px -1px 2px #ffffff;
    }
    .neu-home-btn {
        background: #EFEEEE;
        box-shadow: 8px 8px 16px #d1d1d1, -8px -8px 16px #ffffff;
        border: 1px solid rgba(255,255,255,0.4);
        transition: all 0.3s ease;
    }
    .neu-home-btn:active {
        box-shadow: inset 4px 4px 8px #d1d1d1, inset -4px -4px 8px #ffffff;
        transform: translateY(2px);
    }
</style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="font-display text-text-dark pb-32 relative">
<div class="pt-16 pb-8 flex flex-col items-center justify-center">
<div class="neu-flat rounded-full p-3 flex items-center justify-center mb-5 relative">
<div class="rounded-full h-28 w-28 bg-center bg-cover border-4 border-[#EFEEEE]" style='background-image: url("https://lh3.googleusercontent.com/aida-public/AB6AXuBxcIRi69RC54WPbEGDulKdcriUFDwm80lWD1B-5ZruEY36uWOA1mf1zTsY57By1KyK9VhX20C09h2oyfXX-vRAwjMH6tf-VukEMcaDuHxS1U4irGf8SRpSDJuc9RmbLxoM1jclMGx6HL7gXj_MQXT38ldVhRHHjn4nbp-YUiWOeWCRT2Dkqs8JBSnp-wYP4tMsmfBZz32nVh3rVWfSmPCMCfDpoGoDXafFvHEojIQffjT2nF3MwSP6kAruUKxYsEsf-pPA1I0tQMg"); box-shadow: inset 3px 3px 6px rgba(0,0,0,0.1);'></div>
</div>
<h1 class="text-2xl font-bold text-text-dark tracking-tight">Alex Johnson</h1>
</div>
<div class="px-6 mb-8">
<button class="neu-btn-long w-full p-4 flex items-center justify-between group bg-gradient-to-r from-[#EFEEEE] to-[#F7FAFC]">
<div class="flex items-center gap-4">
<div class="w-10 h-10 rounded-full neu-pressed flex items-center justify-center text-yellow-500 bg-white/20">
<span class="material-symbols-outlined text-[24px]" style="font-variation-settings: 'FILL' 1;">crown</span>
</div>
<div class="flex flex-col items-start">
<span class="font-bold text-black text-lg">升级高级会员</span>
</div>
</div>
<span class="material-symbols-outlined text-gray-400 group-hover:text-yellow-500 transition-colors">chevron_right</span>
</button>
</div>
<div class="px-6 flex flex-col gap-5 mb-10">
<button class="neu-btn-long w-full p-4 flex items-center justify-between group">
<div class="flex items-center gap-4">
<div class="w-10 h-10 rounded-full neu-pressed flex items-center justify-center text-blue-500">
<span class="material-symbols-outlined text-[20px]">person</span>
</div>
<span class="font-medium text-text-dark">Personal Information</span>
</div>
<span class="material-symbols-outlined text-gray-400 group-hover:text-primary transition-colors">chevron_right</span>
</button>
<button class="neu-btn-long w-full p-4 flex items-center justify-between group">
<div class="flex items-center gap-4">
<div class="w-10 h-10 rounded-full neu-pressed flex items-center justify-center text-orange-500">
<span class="material-symbols-outlined text-[20px]">translate</span>
</div>
<span class="font-medium text-text-dark">Language</span>
</div>
<div class="flex items-center gap-2">
<span class="text-xs text-text-gray font-medium">English</span>
<span class="material-symbols-outlined text-gray-400 group-hover:text-primary transition-colors">chevron_right</span>
</div>
</button>
<button class="neu-btn-long w-full p-4 flex items-center justify-between group">
<div class="flex items-center gap-4">
<div class="w-10 h-10 rounded-full neu-pressed flex items-center justify-center text-gray-600">
<span class="material-symbols-outlined text-[20px]">manage_accounts</span>
</div>
<span class="font-medium text-text-dark">Account Settings</span>
</div>
<span class="material-symbols-outlined text-gray-400 group-hover:text-primary transition-colors">chevron_right</span>
</button>
<button class="neu-btn-long w-full p-4 flex items-center justify-between group">
<div class="flex items-center gap-4">
<div class="w-10 h-10 rounded-full neu-pressed flex items-center justify-center text-purple-500">
<span class="material-symbols-outlined text-[20px]">help_center</span>
</div>
<span class="font-medium text-text-dark">Help &amp; Feedback</span>
</div>
<span class="material-symbols-outlined text-gray-400 group-hover:text-primary transition-colors">chevron_right</span>
</button>
<button class="neu-btn-long w-full p-4 flex items-center justify-between group">
<div class="flex items-center gap-4">
<div class="w-10 h-10 rounded-full neu-pressed flex items-center justify-center text-green-500">
<span class="material-symbols-outlined text-[20px]">policy</span>
</div>
<span class="font-medium text-text-dark">Privacy Policy</span>
</div>
<span class="material-symbols-outlined text-gray-400 group-hover:text-primary transition-colors">chevron_right</span>
</button>
<button class="neu-btn-long w-full p-4 flex items-center justify-between group">
<div class="flex items-center gap-4">
<div class="w-10 h-10 rounded-full neu-pressed flex items-center justify-center text-teal-500">
<span class="material-symbols-outlined text-[20px]">info</span>
</div>
<span class="font-medium text-text-dark">About</span>
</div>
<span class="material-symbols-outlined text-gray-400 group-hover:text-primary transition-colors">chevron_right</span>
</button>
</div>
<div class="fixed bottom-8 left-0 right-0 flex items-center justify-center z-50 pointer-events-none">
<button class="neu-home-btn w-16 h-16 rounded-full flex items-center justify-center text-gray-500 hover:text-primary pointer-events-auto">
<span class="material-symbols-outlined text-3xl">home</span>
</button>
</div>

</body></html>

## 订阅页面
<!DOCTYPE html>
<html class="light" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Upgrade to Paid User - Neumorphism</title>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        neu: {
                            base: '#EFEEEE',
                            dark: '#D1D5DB',
                            light: '#FFFFFF',
                        }
                    },
                    fontFamily: {
                        "display": ["Lexend", "sans-serif"],
                    },
                },
            },
        }
    </script>
<style>
        body {
            background-color: #EFEEEE;
        }
        .neu-outset {
            background: #EFEEEE;
            box-shadow: 8px 8px 16px #D1D5DB, 
                       -8px -8px 16px #FFFFFF;
            border-radius: 1.5rem;
        }
        .neu-card-raised {
            background: #EFEEEE;
            box-shadow: 6px 6px 12px #D1D5DB, 
                       -6px -6px 12px #FFFFFF;
            border-radius: 1.25rem;
        }
        .neu-outset-sm {
            background: #EFEEEE;
            box-shadow: 5px 5px 10px #D1D5DB, 
                       -5px -5px 10px #FFFFFF;
            border-radius: 9999px;
        }
        .neu-inset {
            background: #EFEEEE;
            box-shadow: inset 6px 6px 12px #D1D5DB, 
                       inset -6px -6px 12px #FFFFFF;
            border-radius: 9999px;
        }
        .neu-btn-highlight {
            background: #FFFFFF;
            box-shadow: 8px 8px 20px #D1D5DB, 
                       -8px -8px 20px #FFFFFF;
            border-radius: 1rem;
            transition: transform 0.1s ease;
        }
        .neu-btn-highlight:active {
            transform: scale(0.98);
            box-shadow: 6px 6px 15px #D1D5DB, 
                       -6px -6px 15px #FFFFFF;
        }
        .toggle-active {
            background: #EFEEEE;
            box-shadow: 3px 3px 6px #D1D5DB, 
                       -3px -3px 6px #FFFFFF;
        }@keyframes border-glow-flow {
            0% {
                border-color: #ef4444;
                box-shadow: 6px 6px 12px #D1D5DB, -6px -6px 12px #FFFFFF, 0 0 0 rgba(239, 68, 68, 0);
            }
            50% {
                border-color: #f87171;
                box-shadow: 6px 6px 12px #D1D5DB, -6px -6px 12px #FFFFFF, 0 0 12px rgba(239, 68, 68, 0.25);
            }
            100% {
                border-color: #ef4444;
                box-shadow: 6px 6px 12px #D1D5DB, -6px -6px 12px #FFFFFF, 0 0 0 rgba(239, 68, 68, 0);
            }
        }
        .premium-card-active {
            animation: border-glow-flow 3s ease-in-out infinite;
        }
        body {
            min-height: max(884px, 100dvh);
        }
    </style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="text-gray-800 font-display antialiased min-h-screen flex flex-col relative overflow-x-hidden selection:bg-gray-300">
<div class="sticky top-0 z-20 flex items-center justify-between px-6 py-4 bg-[#EFEEEE]/90 backdrop-blur-sm">
<button class="neu-outset-sm w-10 h-10 flex items-center justify-center text-gray-500 hover:text-gray-800 transition-colors">
<span class="material-symbols-outlined" style="font-size: 24px;">chevron_left</span>
</button>
<h1 class="text-sm font-bold tracking-widest text-gray-500 uppercase">Premium Upgrade</h1>
<div class="w-10"></div>
</div>
<div class="flex-1 flex flex-col w-full max-w-md mx-auto px-6 pt-8 pb-32">
<div class="text-center mb-10">
<h2 class="text-2xl font-bold text-gray-900 mb-2">Choose Your Plan</h2>
<p class="text-sm text-gray-500">Unlock your full potential today</p>
</div>
<div class="mb-10 flex justify-center">
<div class="neu-inset p-1.5 flex w-full max-w-[280px] h-14 relative rounded-full">
<div class="absolute right-1.5 top-1.5 bottom-1.5 w-[calc(50%-6px)] toggle-active rounded-full z-0"></div>
<button class="flex-1 relative z-10 flex items-center justify-center text-xs font-semibold text-gray-400 hover:text-gray-600 transition-colors">
                    Monthly
                </button>
<button class="flex-1 relative z-10 flex items-center justify-center text-xs font-bold text-gray-900">
                    Yearly
                    <span class="ml-1 text-[10px] text-red-500 font-bold">-20%</span>
</button>
</div>
</div>
<div class="space-y-6">
<div class="neu-card-raised p-6 flex flex-col gap-3 border-2 border-transparent transition-colors cursor-pointer group hover:border-gray-300/50">
<div class="flex justify-between items-baseline">
<h3 class="text-lg font-bold text-gray-900">Basic</h3>
<div class="text-2xl font-bold text-gray-900">¥199<span class="text-xs font-normal text-gray-500 ml-1">/yr</span></div>
</div>
<div class="w-full h-px bg-gray-300/50"></div>
<p class="text-sm text-gray-500 font-medium leading-relaxed">
                    Essential access to standard learning materials and basic community support.
                </p>
</div>
<div class="neu-card-raised premium-card-active p-6 flex flex-col gap-3 relative border-2 border-red-500 cursor-pointer">
<div class="absolute -top-3 left-6">
<span class="px-3 py-1 rounded-full bg-[#EFEEEE] shadow-[2px_2px_5px_#D1D5DB,-2px_-2px_5px_#FFFFFF] text-[10px] font-extrabold text-blue-500 uppercase tracking-wider">
                        Most Popular
                     </span>
</div>
<div class="flex justify-between items-baseline mt-1">
<h3 class="text-lg font-bold text-gray-900">Premium</h3>
<div class="text-right">
<div class="text-2xl font-bold text-gray-900">¥299<span class="text-xs font-normal text-gray-500 ml-1">/yr</span></div>
</div>
</div>
<div class="w-full h-px bg-gray-300/50"></div>
<p class="text-sm text-gray-500 font-medium leading-relaxed">
                    Advanced AI correction, unlimited practice sets, and priority 24/7 tutor access.
                </p>
</div>
<div class="neu-card-raised p-6 flex flex-col gap-3 border-2 border-transparent transition-colors cursor-pointer group hover:border-gray-300/50">
<div class="flex justify-between items-baseline">
<h3 class="text-lg font-bold text-gray-900">Supreme</h3>
<div class="text-2xl font-bold text-gray-900">¥1999<span class="text-xs font-normal text-gray-500 ml-1">/yr</span></div>
</div>
<div class="w-full h-px bg-gray-300/50"></div>
<p class="text-sm text-gray-500 font-medium leading-relaxed">
                   All-inclusive access with 1-on-1 expert coaching sessions and exclusive masterclasses.
                </p>
</div>
</div>
</div>
<div class="fixed bottom-0 left-0 right-0 z-30 p-6 bg-[#EFEEEE]/80 backdrop-blur-md border-t border-white/20 shadow-[0_-10px_40px_rgba(255,255,255,0.5)]">
<div class="max-w-md mx-auto">
<button class="w-full h-14 neu-btn-highlight flex items-center justify-center gap-2 group">
<span class="text-black font-bold text-lg">Upgrade Now</span>
<span class="material-symbols-outlined text-black group-hover:translate-x-1 transition-transform" style="font-size: 20px;">arrow_forward</span>
</button>
<div class="mt-4 flex justify-center items-center gap-1.5 text-[10px] text-gray-400">
<span class="material-symbols-outlined" style="font-size: 14px;">lock</span>
<span>Secure payment encrypted by SSL</span>
</div>
</div>
</div>

</body></html>

# 认证
## 登录/注册
<!DOCTYPE html>
<html class="light" lang="en"><head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>Login - No Teacher</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<script id="tailwind-config">
    tailwind.config = {
        darkMode: "class",
        theme: {
            extend: {
                colors: {
                    "neu-base": "#EFEEEE",
                    "primary": "#3B82F6",
                    "text-dark": "#324054",
                    "text-gray": "#94A3B8",
                    "emerald-neu": "#10B981",
                    "red-neu": "#FF3B30",
                },
                fontFamily: {
                    "display": ["Lexend", "Noto Sans", "sans-serif"]
                },
                boxShadow: {
                    'neu-flat': '6px 6px 12px #C5C9D2, -6px -6px 12px #FFFFFF',
                    'neu-pressed': 'inset 4px 4px 8px #C5C9D2, inset -4px -4px 8px #FFFFFF',
                    'neu-btn': '8px 8px 16px #C5C9D2, -8px -8px 16px #FFFFFF',
                    'neu-btn-hover': '10px 10px 20px #C5C9D2, -10px -10px 20px #FFFFFF',
                    'neu-input': 'inset 3px 3px 6px #C5C9D2, inset -3px -3px 6px #FFFFFF',
                    'neu-concave': 'inset 6px 6px 12px #C5C9D2, inset -6px -6px 12px #FFFFFF',
                    'neu-floating': '12px 12px 24px #C5C9D2, -12px -12px 24px #FFFFFF',
                    'neu-toggle': '4px 4px 8px #C5C9D2, -4px -4px 8px #FFFFFF',
                }
            },
        },
    }
</script>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&amp;display=swap" rel="stylesheet"/>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&amp;display=swap" rel="stylesheet"/>
<style>
    .no-scrollbar::-webkit-scrollbar {
        display: none;
    }
    .no-scrollbar {
        -ms-overflow-style: none;
        scrollbar-width: none;
    }
    body {
        min-height: 100vh;
        background-color: #EFEEEE;
    }
    .neu-transition {
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
</style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
</style>
<style>
    body {
      min-height: max(884px, 100dvh);
    }
  </style>
  </head>
<body class="font-display text-text-dark antialiased selection:bg-primary/20 flex flex-col h-screen overflow-hidden bg-neu-base">
<div class="relative w-full h-full flex flex-col px-8 py-4 overflow-y-auto no-scrollbar">
<div class="flex flex-col items-center justify-center pt-16 pb-12">
<h1 class="text-gray-400/80 text-2xl font-bold leading-tight text-center tracking-[0.2em] uppercase" style="text-shadow: 3px 3px 6px #C5C9D2, -3px -3px 6px #FFFFFF;">NO TEACHER</h1>
</div>
<div class="flex p-2 mb-10 rounded-2xl bg-neu-base shadow-neu-pressed w-full items-center">
<button class="flex-1 h-11 rounded-xl bg-neu-base shadow-neu-toggle text-text-dark font-bold text-sm tracking-wide neu-transition flex items-center justify-center transform active:scale-[0.98] border border-white/60" type="button">
            Mobile
        </button>
<button class="flex-1 h-11 rounded-xl bg-transparent text-gray-400 font-medium text-sm tracking-wide neu-transition hover:text-text-dark flex items-center justify-center" type="button">
            Email
        </button>
</div>
<div class="flex flex-col gap-7">
<div class="relative group">
<input class="flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-2xl text-text-dark focus:outline-none bg-neu-base shadow-neu-input border-none h-14 placeholder:text-gray-400/70 px-6 text-sm font-medium transition-all focus:ring-0 focus:shadow-neu-concave" placeholder="Mobile Number" type="tel" value=""/>
</div>
<div class="relative group">
<input class="flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-2xl text-text-dark focus:outline-none bg-neu-base shadow-neu-input border-none h-14 placeholder:text-gray-400/70 pl-6 pr-32 text-sm font-medium transition-all focus:ring-0 focus:shadow-neu-concave" maxlength="6" placeholder="Verification Code" type="text"/>
<button class="absolute right-2 top-1/2 -translate-y-1/2 h-10 px-5 rounded-xl bg-[#F9FAFB] shadow-neu-flat active:shadow-neu-pressed text-red-neu text-xs font-bold transition-all hover:-translate-y-[calc(50%+1px)] border border-white/70" type="button">
                Get Code
            </button>
</div>
<button class="flex w-full items-center justify-center rounded-2xl bg-neu-base text-text-dark h-14 text-base font-bold tracking-wide shadow-neu-btn hover:shadow-neu-btn-hover active:shadow-neu-pressed active:scale-[0.98] transition-all duration-300 mt-4 uppercase border border-white/60">
            Login / Sign Up
        </button>
</div>
<div class="flex items-center gap-4 py-12 opacity-80">
<div class="h-px flex-1 bg-gray-300 shadow-[0_1px_0_rgba(255,255,255,0.8)]"></div>
<p class="text-gray-400 text-[10px] font-bold uppercase tracking-widest text-shadow-sm">Or login with</p>
<div class="h-px flex-1 bg-gray-300 shadow-[0_1px_0_rgba(255,255,255,0.8)]"></div>
</div>
<div class="flex gap-12 justify-center mb-8">
<button class="flex h-16 w-16 items-center justify-center rounded-full bg-neu-base shadow-neu-flat hover:shadow-neu-btn-hover active:shadow-neu-pressed active:scale-95 transition-all duration-300 text-gray-600 group border border-white/40">
<span class="material-symbols-outlined text-[28px] group-hover:scale-110 transition-transform text-gray-500">chat</span>
</button>
<button class="flex h-16 w-16 items-center justify-center rounded-full bg-neu-base shadow-neu-flat hover:shadow-neu-btn-hover active:shadow-neu-pressed active:scale-95 transition-all duration-300 group border border-white/40">
<img alt="Apple Login" class="w-6 h-6 opacity-60 grayscale group-hover:opacity-80 group-hover:scale-110 transition-all" src="https://lh3.googleusercontent.com/aida-public/AB6AXuCYFvfTr8o30f1odTVp-R6TP_CjWjOuibw0ADznewKzvA0mTkvLrhzTSLF-6LgAtE8zoVSPoM5vsF6JzplLpqFqFaWD7eSK6GIdO4kIGQRKHCO-QAUI9pxCz1m6N09hsjOzLGw_LTsWYZp2QGmpncgrNlqvQJK1sh9ETzCnIuqgvfZAMPnuRvYR3N1dCrJwouM5KSDkGqc5JUFYKE0Ljsr9nm7CZS22c3VBXvrD_xsU7zsrY4Tl_Ln2Oo82c_cNGmoFRAo4PttkBY0"/>
</button>
</div>
<div class="mt-auto pb-8 text-center">
<label class="flex items-start justify-center gap-3 cursor-pointer group select-none">
<div class="relative flex items-center mt-0.5">
<input class="peer h-5 w-5 rounded border-gray-300 text-primary focus:ring-primary/50 bg-neu-base shadow-neu-input checked:shadow-neu-pressed cursor-pointer appearance-none checked:bg-primary checked:border-transparent transition-all" type="checkbox"/>
<span class="material-symbols-outlined absolute inset-0 text-white text-[16px] pointer-events-none opacity-0 peer-checked:opacity-100 transition-opacity flex items-center justify-center">check</span>
</div>
<span class="text-xs text-gray-400 text-left leading-relaxed max-w-[260px]">
                I agree to the <a class="text-text-dark font-bold hover:underline decoration-2 underline-offset-2 transition-colors" href="#">Terms of Service</a> and <a class="text-text-dark font-bold hover:underline decoration-2 underline-offset-2 transition-colors" href="#">Privacy Policy</a>
</span>
</label>
</div>
</div>

</body></html>

## 未登录拦截弹窗
这个目前我还没有设计，需要根据当前的整个视觉风格来完成设计，如果没有必要，可以和登录/注册 页面一致
