/* ============================================================
 *  wika.y — Bison Parser for WIKA
 *
 *  Sinusuportahan:
 *    bilang  — integer (64-bit word)
 *    titik   — single character (stored as ASCII integer)
 *
 *  Output: valid EduMIPS64 assembly (.data + .code sections)
 *
 *  EduMIPS64 SYSCALL table used:
 *    SYSCALL 0  — exit / halt
 *    SYSCALL 1  — print integer (value in r14)
 *    SYSCALL 11 — print character (ASCII value in r14)
 *
 *  Nathaniel B. Ministros | CSC 112 BNO1
 * ============================================================ */

%{
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <stdarg.h>
#ifdef _WIN32
#include <windows.h>
#endif

extern int  yylex();
extern int  yyline;
void yyerror(const char *msg);

/* ============================================================
 *  CONSTANTS
 * ============================================================ */
#define MAX_VARS   100
#define MAX_ERRORS 200

/* ============================================================
 *  DATA TYPES
 *  KIND_BILANG — whole integer  (bilang x = 5)
 *  KIND_TITIK  — single char    (titik c = 'A')
 *    titik stores ASCII value as integer; arithmetic works;
 *    ipakita prints the character via SYSCALL 11.
 *
 *  IMPORTANT:
 *    bilang is stored as .word64 (8-byte) in the .data section.
 *    titik  is stored as .byte  (1-byte) in the .data section.
 *  Load/store instructions used accordingly:
 *    bilang: ld / sd  (opcode 0x37 / 0x3F)
 *    titik:  lb / sb  (opcode 0x20 / 0x28)
 * ============================================================ */
typedef enum { KIND_BILANG, KIND_TITIK } VarKind;

/* ============================================================
 *  ERROR LISTS
 * ============================================================ */
char sem_errors[MAX_ERRORS][512];
int  sem_error_count   = 0;
int  parse_error_count = 0;

void add_sem_error(const char *fmt, ...) {
    if (sem_error_count >= MAX_ERRORS) return;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(sem_errors[sem_error_count], 512, fmt, ap);
    va_end(ap);
    sem_error_count++;
}

/* ============================================================
 *  SYMBOL TABLE
 * ============================================================ */
typedef struct {
    char    name[64];
    VarKind kind;
    long    value;       /* current interpreter value  */
    long    init_value;  /* value at declaration        */
    int     offset;      /* byte offset in .data section */
} Var;

Var sym[MAX_VARS];
int sym_count = 0;

/* Running byte offset tracker for .data section.
 *   bilang (.word64) = 8 bytes
 *   titik  (.byte)   = 1 byte
 */
int next_data_offset = 0;

int find_var(const char *name) {
    for (int i = 0; i < sym_count; i++)
        if (strcmp(sym[i].name, name) == 0) return i;
    return -1;
}

int add_var(const char *name, VarKind kind) {
    int idx = find_var(name);
    if (idx != -1) {
        add_sem_error(
            "[Linya %d] '%s' ay naideklara na.",
            yyline, name);
        return idx;
    }
    if (sym_count >= MAX_VARS) {
        add_sem_error("[Linya %d] Naabot na ang MAX_VARS.", yyline);
        return -1;
    }
    strncpy(sym[sym_count].name, name, 63);
    sym[sym_count].kind       = kind;
    sym[sym_count].value      = 0;
    sym[sym_count].init_value = 0;

    /* Assign the current running offset, then advance it */
    sym[sym_count].offset = next_data_offset;
    if (kind == KIND_TITIK)
        next_data_offset += 1;   /* .byte  = 1 byte */
    else
        next_data_offset += 8;   /* .word64 = 8 bytes */

    return sym_count++;
}

VarKind current_kind = KIND_BILANG;

/* ============================================================
 *  REGISTER ALLOCATOR
 *
 *  EduMIPS64 general-purpose registers: r0-r31
 *    r0  = always zero (hardwired)
 *    r14 = SYSCALL argument register (reserved, do not allocate)
 *    r31 = link register (do not allocate)
 *
 *  We allocate from r1-r13 and r15-r30, cycling round-robin.
 *  No register caching across statements — every load is explicit
 *  to avoid stale-value bugs when registers are reused.
 * ============================================================ */
int next_reg = 1;

int alloc_reg() {
    if (next_reg == 14) next_reg = 15;
    if (next_reg >= 31) next_reg = 1;
    return next_reg++;
}

/* ============================================================
 *  MIPS MACHINE CODE ENCODERS
 *
 *  R-type  [ op=0(6) | rs(5) | rt(5) | rd(5) | sa(5) | funct(6) ]
 *  I-type  [ op(6)   | rs(5) | rt(5) | immediate(16)             ]
 * ============================================================ */
uint32_t encode_r(int rs, int rt, int rd, int sa, int funct) {
    return ((uint32_t)(rs    & 0x1F) << 21)
         | ((uint32_t)(rt    & 0x1F) << 16)
         | ((uint32_t)(rd    & 0x1F) << 11)
         | ((uint32_t)(sa    & 0x1F) << 6)
         | ((uint32_t)(funct & 0x3F));
}

uint32_t encode_i(int op, int rs, int rt, int imm) {
    return ((uint32_t)(op  & 0x3F)   << 26)
         | ((uint32_t)(rs  & 0x1F)   << 21)
         | ((uint32_t)(rt  & 0x1F)   << 16)
         | ((uint32_t)(imm & 0xFFFF));
}

/* ============================================================
 *  BINARY PRINTERS — with field separators for display
 * ============================================================ */
void print_bits_r(uint32_t ins) {
    int sep[] = {26, 21, 16, 11, 6};
    for (int b = 31; b >= 0; b--) {
        putchar(((ins >> b) & 1) ? '1' : '0');
        for (int j = 0; j < 5; j++)
            if (b == sep[j]) { putchar(' '); break; }
    }
    putchar('\n');
}

void print_bits_i(uint32_t ins) {
    int sep[] = {26, 21, 16};
    for (int b = 31; b >= 0; b--) {
        putchar(((ins >> b) & 1) ? '1' : '0');
        for (int j = 0; j < 3; j++)
            if (b == sep[j]) { putchar(' '); break; }
    }
    putchar('\n');
}

void show_r(uint32_t ins) {
    printf("; HEX:    %08X\n", ins);
    printf("; BINARY: ");
    print_bits_r(ins);
}

void show_i(uint32_t ins) {
    printf("; HEX:    %08X\n", ins);
    printf("; BINARY: ");
    print_bits_i(ins);
}

/* ============================================================
 *  EMIT HELPERS
 *
 *  EduMIPS64 memory conventions:
 *    bilang variables declared as .word64 (8 bytes).
 *    titik  variables declared as .byte   (1 byte).
 *
 *  CORRECTED opcodes for EduMIPS64 64-bit load/store:
 *    ld  rd, offset(r0)   opcode = 0x37   (NOT 0x23 which is lw)
 *    sd  rs, offset(r0)   opcode = 0x3F   (NOT 0x2B which is sw)
 *    lb  rd, offset(r0)   opcode = 0x20   (unchanged)
 *    sb  rs, offset(r0)   opcode = 0x28   (unchanged)
 *
 *  The offset field encodes the variable's byte offset in .data,
 *  which EduMIPS64 resolves from the label at assembly time.
 *
 *  Load immediate (I-type, opcode 0x18 = DADDI):
 *    daddi rt, r0, imm   ; rt = 0 + sign_extend(imm)  — NO '#' prefix!
 *    RULE: rs (source) and rt (dest) MUST be different registers.
 *    Always use r0 as the source when loading a literal immediate.
 *
 *  Arithmetic (EduMIPS64-supported only):
 *    daddu rd, rs, rt   funct=0x2D  64-bit add unsigned
 *    dsub  rd, rs, rt   funct=0x2E  64-bit subtract signed
 *    mult  rs, rt       funct=0x18  32-bit multiply -> HI/LO
 *    div   rs, rt       funct=0x1A  32-bit divide   -> HI/LO
 *    mflo  rd           funct=0x12  move LO to rd
 *
 *  SYSCALL argument register: r14
 *    daddu r14, rX, r0  ; move rX into r14
 *    SYSCALL 1          ; print integer in r14
 *    SYSCALL 11         ; print char (ASCII) in r14
 *    SYSCALL 0          ; halt
 * ============================================================ */

/* emit: rt = immediate value  (daddi rt, r0, imm) */
void emit_load_imm(int rd, long ival) {
    printf("    daddi r%d, r0, %ld\n", rd, ival);
    show_i(encode_i(0x18, 0, rd, (int)(ival & 0xFFFF)));
    printf("\n");
}

/* emit: rd = value of named variable
 *   bilang: ld rd, offset(r0)   opcode=0x37
 *   titik:  lb rd, offset(r0)   opcode=0x20
 *
 *  The offset is the variable's byte position in .data,
 *  matching what EduMIPS64 resolves the label to at runtime.
 */
void emit_load_var(int rd, const char *name) {
    int idx = find_var(name);
    if (idx != -1 && sym[idx].kind == KIND_TITIK) {
        printf("    lb r%d, %s(r0)\n", rd, name);
        show_i(encode_i(0x20, 0, rd, sym[idx].offset));
    } else {
        printf("    ld r%d, %s(r0)\n", rd, name);
        /* FIX: opcode 0x37 = ld (64-bit), was incorrectly 0x23 (lw, 32-bit) */
        show_i(encode_i(0x37, 0, rd, sym[idx].offset));
    }
    printf("\n");
}

/* emit: store rs into named variable
 *   bilang: sd rs, offset(r0)   opcode=0x3F
 *   titik:  sb rs, offset(r0)   opcode=0x28
 */
void emit_store(int rs, const char *name) {
    int idx = find_var(name);
    if (idx != -1 && sym[idx].kind == KIND_TITIK) {
        printf("    sb r%d, %s(r0)\n", rs, name);
        show_i(encode_i(0x28, 0, rs, sym[idx].offset));
    } else {
        printf("    sd r%d, %s(r0)\n", rs, name);
        /* FIX: opcode 0x3F = sd (64-bit), was incorrectly 0x2B (sw, 32-bit) */
        show_i(encode_i(0x3F, 0, rs, sym[idx].offset));
    }
    printf("\n");
}

/* ============================================================
 *  SYSCALL EMITTER
 *
 *  SYSCALL is a special R-type instruction:
 *    [ op=0(6) | code(20) | funct=0x0C(6) ]
 *
 *  The 20-bit 'code' field (bits 25-6) carries the syscall number.
 *  op=0 and funct=0x0C are constant for all SYSCALLs.
 *
 *  Pre-computed constants used in this program:
 *    SYSCALL  0  → 0x0000000C  (halt / exit)
 *    SYSCALL  1  → 0x0000004C  (print integer in r14)
 *    SYSCALL 11  → 0x000002CC  (print char ASCII in r14)
 * ============================================================ */
void emit_syscall(int n) {
    uint32_t ins = ((uint32_t)(n & 0xFFFFF) << 6) | 0x0C;
    printf("    SYSCALL %d\n", n);
    printf("; HEX:    %08X\n", ins);
    printf("; BINARY: ");
    /* Three logical fields: op(6) | code(20) | funct(6) */
    int sep[] = {26, 6};
    for (int b = 31; b >= 0; b--) {
        putchar(((ins >> b) & 1) ? '1' : '0');
        for (int j = 0; j < 2; j++)
            if (b == sep[j]) { putchar(' '); break; }
    }
    putchar('\n');
    printf("\n");
}

/* emit arithmetic R-type or multiply/divide with mflo */
void emit_arith(const char *op, int rd, int rs, int rt) {
    uint32_t ins = 0;
    if (strcmp(op, "+") == 0) {
        printf("    daddu r%d, r%d, r%d\n", rd, rs, rt);
        ins = encode_r(rs, rt, rd, 0, 0x2D);
        show_r(ins);
        printf("\n");
    } else if (strcmp(op, "-") == 0) {
        printf("    dsub r%d, r%d, r%d\n", rd, rs, rt);
        ins = encode_r(rs, rt, rd, 0, 0x2E);
        show_r(ins);
        printf("\n");
    } else if (strcmp(op, "*") == 0) {
        printf("    mult r%d, r%d\n", rs, rt);
        ins = encode_r(rs, rt, 0, 0, 0x18);
        show_r(ins);
        printf("\n");
        printf("    mflo r%d\n", rd);
        ins = encode_r(0, 0, rd, 0, 0x12);
        show_r(ins);
        printf("\n");
    } else if (strcmp(op, "/") == 0) {
        printf("    div r%d, r%d\n", rs, rt);
        ins = encode_r(rs, rt, 0, 0, 0x1A);
        show_r(ins);
        printf("\n");
        printf("    mflo r%d\n", rd);
        ins = encode_r(0, 0, rd, 0, 0x12);
        show_r(ins);
        printf("\n");
    }
}

/* ============================================================
 *  AST NODE
 * ============================================================ */
typedef struct Node {
    int    kind;    /* 0=number, 1=variable, 2=operator */
    long   num;
    char   text[64];
    struct Node *L, *R;
} Node;

Node *new_num(long v) {
    Node *n = calloc(1, sizeof(Node));
    n->kind = 0; n->num = v; return n;
}
Node *new_var(const char *s) {
    Node *n = calloc(1, sizeof(Node));
    n->kind = 1; strncpy(n->text, s, 63); return n;
}
Node *new_op(const char *op, Node *l, Node *r) {
    Node *n = calloc(1, sizeof(Node));
    n->kind = 2; strncpy(n->text, op, 63);
    n->L = l; n->R = r; return n;
}
void free_tree(Node *n) {
    if (!n) return;
    free_tree(n->L); free_tree(n->R); free(n);
}

/* ============================================================
 *  EVALUATOR — computes integer result at interpretation time
 * ============================================================ */
long eval(Node *n) {
    if (!n) return 0;
    if (n->kind == 0) return n->num;
    if (n->kind == 1) {
        int i = find_var(n->text);
        return (i == -1) ? 0 : sym[i].value;
    }
    long l = eval(n->L), r = eval(n->R);
    if (strcmp(n->text, "+") == 0) return l + r;
    if (strcmp(n->text, "-") == 0) return l - r;
    if (strcmp(n->text, "*") == 0) return l * r;
    if (strcmp(n->text, "/") == 0) {
        if (r == 0) {
            add_sem_error("[Linya %d] Paghahati sa zero.", yyline);
            return 0;
        }
        return l / r;
    }
    return 0;
}

/* ============================================================
 *  CODE EMITTER — emits MIPS for an expression tree,
 *  returns the register holding the result.
 * ============================================================ */
int emit_code(Node *n) {
    if (!n) return 0;

    if (n->kind == 0) {
        int r = alloc_reg();
        emit_load_imm(r, n->num);
        return r;
    }

    if (n->kind == 1) {
        int i = find_var(n->text);
        if (i == -1) {
            add_sem_error("[Linya %d] '%s' ay hindi naideklara.",
                          yyline, n->text);
            return 0;
        }
        int r = alloc_reg();
        emit_load_var(r, sym[i].name);
        return r;
    }

    if (n->kind == 2) {
        int lr = emit_code(n->L);
        int rr = emit_code(n->R);
        int dr = alloc_reg();
        emit_arith(n->text, dr, lr, rr);
        return dr;
    }

    return 0;
}

/* ============================================================
 *  do_assign — evaluate expression, emit code, store result
 * ============================================================ */
void do_assign(int idx, Node *expr) {
    sym[idx].value = eval(expr);
    int r = emit_code(expr);
    emit_store(r, sym[idx].name);
}

%}

/* ============================================================
 *  BISON TOKEN DECLARATIONS
 * ============================================================ */
%union {
    long    ival;
    char   *str;
    void   *node;
}

%token SIMULA TAPOS IPAKITA
%token BILANG TITIK
%token DAGDAG_SET BAWAS_SET DAGDAG_ISA BAWAS_ISA
%token PLUS MINUS BESES HATI KATUMBAS
%token L_PAREN R_PAREN KUWIT BAGONG_LINYA

%token <ival> NUMERO
%token <str>  IDENTIFIER CHAR_LIT

%type <node> ekspresyon termino salik

%left PLUS MINUS
%left BESES HATI
%right UMINUS

%%

/* ============================================================
 *  GRAMMAR RULES
 * ============================================================ */

programa
    : SIMULA talaan_pahayag TAPOS optnl
    | SIMULA TAPOS optnl
    ;

optnl
    : /* empty */
    | newlines
    ;

newlines
    : BAGONG_LINYA
    | newlines BAGONG_LINYA
    ;

talaan_pahayag
    : pahayag
    | talaan_pahayag pahayag
    ;

pahayag
    : deklarasyon BAGONG_LINYA
    | takda BAGONG_LINYA
    | palabas BAGONG_LINYA
    | BAGONG_LINYA
    ;

/* ============================================================
 *  DECLARATION
 * ============================================================ */
deklarasyon
    : uri talaan_item
    ;

uri
    : BILANG  { current_kind = KIND_BILANG; }
    | TITIK   { current_kind = KIND_TITIK;  }
    ;

talaan_item
    : item
    | talaan_item KUWIT item
    ;

item
    /* Plain declaration: bilang x  (defaults to 0) */
    : IDENTIFIER
        {
            add_var($1, current_kind);
            free($1);
        }

    /* Declaration with numeric initializer: bilang x = 5+3
     *
     * FIX: Only evaluate the expression and store the result in the
     * symbol table so main() can emit it in the .data section as the
     * static initializer (.word64 / .byte).  Do NOT call do_assign()
     * here, because that emits a redundant daddi + sd pair into .code
     * for a value that is already baked into .data at assembly time.
     */
    | IDENTIFIER KATUMBAS ekspresyon
        {
            int idx = add_var($1, current_kind);
            Node *expr = (Node*)$3;
            if (idx >= 0) {
                sym[idx].value      = eval(expr);
                sym[idx].init_value = sym[idx].value;
                /* No emit_code / emit_store — .data handles the init */
            }
            free_tree(expr);
            free($1);
        }

    /* Declaration with char literal: titik c = 'A'
     *
     * FIX: Same rationale — just record the ASCII value so main()
     * can write it into .data as a .byte initializer.  No runtime
     * daddi + sb needed.
     */
    | IDENTIFIER KATUMBAS CHAR_LIT
        {
            int idx = add_var($1, current_kind);
            if (idx >= 0) {
                if (current_kind != KIND_TITIK) {
                    add_sem_error(
                        "[Linya %d] '%s' ay hindi 'titik'; char literal ay para lamang sa 'titik'.",
                        yyline, $1);
                } else {
                    long ascii = (long)(unsigned char)$3[0];
                    sym[idx].value      = ascii;
                    sym[idx].init_value = ascii;
                    /* No emit_load_imm / emit_store — .data handles the init */
                }
            }
            free($1); free($3);
        }
    ;

/* ============================================================
 *  ASSIGNMENT
 * ============================================================ */
takda
    : talaan_takda
    ;

talaan_takda
    : item_takda
    | talaan_takda KUWIT item_takda
    ;

item_takda
    /* x = expr */
    : IDENTIFIER KATUMBAS ekspresyon
        {
            int idx = find_var($1);
            if (idx == -1) {
                add_sem_error(
                    "[Linya %d] '%s' ay hindi naideklara.",
                    yyline, $1);
            } else {
                Node *expr = (Node*)$3;
                do_assign(idx, expr);
                free_tree(expr);
            }
            free($1);
        }

    /* titik c = 'B' (char reassignment) */
    | IDENTIFIER KATUMBAS CHAR_LIT
        {
            int idx = find_var($1);
            if (idx == -1) {
                add_sem_error("[Linya %d] '%s' ay hindi naideklara.",
                              yyline, $1);
            } else if (sym[idx].kind != KIND_TITIK) {
                add_sem_error("[Linya %d] '%s' ay hindi 'titik'.",
                              yyline, $1);
            } else {
                sym[idx].value = (long)(unsigned char)$3[0];
                int r = alloc_reg();
                emit_load_imm(r, sym[idx].value);
                emit_store(r, sym[idx].name);
            }
            free($1); free($3);
        }

    /* x += expr */
    | IDENTIFIER DAGDAG_SET ekspresyon
        {
            int idx = find_var($1);
            if (idx == -1) {
                add_sem_error("[Linya %d] '%s' ay hindi naideklara.",
                              yyline, $1);
            } else {
                Node *expr = (Node*)$3;
                long rhs_val = eval(expr);
                sym[idx].value += rhs_val;

                int old_r = alloc_reg();
                emit_load_var(old_r, sym[idx].name);

                int rhs_r = emit_code(expr);
                int res_r = alloc_reg();
                emit_arith("+", res_r, old_r, rhs_r);
                emit_store(res_r, sym[idx].name);

                free_tree(expr);
            }
            free($1);
        }

    /* x -= expr */
    | IDENTIFIER BAWAS_SET ekspresyon
        {
            int idx = find_var($1);
            if (idx == -1) {
                add_sem_error("[Linya %d] '%s' ay hindi naideklara.",
                              yyline, $1);
            } else {
                Node *expr = (Node*)$3;
                long rhs_val = eval(expr);
                sym[idx].value -= rhs_val;

                int old_r = alloc_reg();
                emit_load_var(old_r, sym[idx].name);

                int rhs_r = emit_code(expr);
                int res_r = alloc_reg();
                emit_arith("-", res_r, old_r, rhs_r);
                emit_store(res_r, sym[idx].name);

                free_tree(expr);
            }
            free($1);
        }

    /* x++
     *
     * EduMIPS64-safe pattern:
     *   ld    r_old, x(r0)        ; load current value
     *   daddi r_new, r_old, 1     ; r_new = r_old + 1  (rs != rt, no #)
     *   sd    r_new, x(r0)        ; store back
     */
    | IDENTIFIER DAGDAG_ISA
        {
            int idx = find_var($1);
            if (idx == -1) {
                add_sem_error("[Linya %d] '%s' ay hindi naideklara.",
                              yyline, $1);
            } else {
                sym[idx].value += 1;
                int r_old = alloc_reg();
                int r_new = alloc_reg();
                emit_load_var(r_old, sym[idx].name);
                printf("    daddi r%d, r%d, 1\n", r_new, r_old);
                show_i(encode_i(0x18, r_old, r_new, 1));
                printf("\n");
                emit_store(r_new, sym[idx].name);
            }
            free($1);
        }

    /* x--
     *
     * EduMIPS64-safe pattern:
     *   ld    r_old, x(r0)        ; load current value
     *   daddi r_new, r_old, -1    ; r_new = r_old - 1  (rs != rt, no #)
     *   sd    r_new, x(r0)        ; store back
     */
    | IDENTIFIER BAWAS_ISA
        {
            int idx = find_var($1);
            if (idx == -1) {
                add_sem_error("[Linya %d] '%s' ay hindi naideklara.",
                              yyline, $1);
            } else {
                sym[idx].value -= 1;
                int r_old = alloc_reg();
                int r_new = alloc_reg();
                emit_load_var(r_old, sym[idx].name);
                printf("    daddi r%d, r%d, -1\n", r_new, r_old);
                show_i(encode_i(0x18, r_old, r_new, (uint16_t)(-1)));
                printf("\n");
                emit_store(r_new, sym[idx].name);
            }
            free($1);
        }
    ;

/* ============================================================
 *  PRINT STATEMENT
 *
 *  EduMIPS64 SYSCALL conventions:
 *    r14 is the argument register for all print SYSCALLs.
 *    Move the value into r14 via:  daddu r14, rX, r0
 *
 *    SYSCALL 1  — print integer (value in r14)
 *    SYSCALL 11 — print character (ASCII value in r14)
 *    SYSCALL 0  — exit / halt
 * ============================================================ */
palabas
    : IPAKITA L_PAREN argumento R_PAREN
    ;

argumento
    /* ipakita(expression) — covers IDENTIFIER, NUMERO, arithmetic, and all expressions.
     * IDENTIFIER alone is handled here because salik → IDENTIFIER is part of ekspresyon.
     * We detect a single-variable expression to use the correct SYSCALL (1=int, 11=char).
     */
    : ekspresyon
        {
            Node *expr = (Node*)$1;
            long result = eval(expr);

            if (expr->kind == 1) {
                /* Single variable reference — use its declared kind for syscall */
                int idx = find_var(expr->text);
                if (idx == -1) {
                    add_sem_error(
                        "[Linya %d] '%s' ay hindi naideklara.",
                        yyline, expr->text);
                } else {
                    printf("; ipakita(%s)\n", expr->text);
                    int r = alloc_reg();
                    emit_load_var(r, sym[idx].name);
                    printf("    daddu r14, r%d, r0\n", r);
                    show_r(encode_r(r, 0, 14, 0, 0x2D));
                    printf("\n");
                    if (sym[idx].kind == KIND_TITIK) {
                        emit_syscall(11);
                        printf("; OUTPUT: %c\n", (char)sym[idx].value);
                    } else {
                        emit_syscall(1);
                        printf("; OUTPUT: %ld\n", sym[idx].value);
                    }
                }
            } else {
                /* General expression (numeric literal, arithmetic, etc.) */
                printf("; ipakita(expression)\n");
                int r = emit_code(expr);
                printf("    daddu r14, r%d, r0\n", r);
                show_r(encode_r(r, 0, 14, 0, 0x2D));
                printf("\n");
                emit_syscall(1);
                printf("; OUTPUT: %ld\n", result);
            }

            free_tree(expr);
        }

    /* ipakita('c') */
    | CHAR_LIT
        {
            long ascii = (long)(unsigned char)$1[0];
            printf("; ipakita('%s')\n", $1);
            int r = alloc_reg();
            emit_load_imm(r, ascii);
            printf("    daddu r14, r%d, r0\n", r);
            show_r(encode_r(r, 0, 14, 0, 0x2D));
            printf("\n");
            emit_syscall(11);
            printf("; OUTPUT: %s\n", $1);
            free($1);
        }
    ;

/* ============================================================
 *  EXPRESSIONS
 * ============================================================ */

ekspresyon
    : ekspresyon PLUS termino
        { $$ = (void*)new_op("+", (Node*)$1, (Node*)$3); }
    | ekspresyon MINUS termino
        { $$ = (void*)new_op("-", (Node*)$1, (Node*)$3); }
    | termino
        { $$ = $1; }
    ;

termino
    : termino BESES salik
        { $$ = (void*)new_op("*", (Node*)$1, (Node*)$3); }
    | termino HATI salik
        { $$ = (void*)new_op("/", (Node*)$1, (Node*)$3); }
    | salik
        { $$ = $1; }
    ;

salik
    : NUMERO
        { $$ = (void*)new_num((long)$1); }

    | IDENTIFIER
        {
            if (find_var($1) == -1) {
                add_sem_error(
                    "[Linya %d] '%s' ay hindi naideklara.",
                    yyline, $1);
            }
            $$ = (void*)new_var($1);
            free($1);
        }

    | L_PAREN ekspresyon R_PAREN
        { $$ = $2; }

    | MINUS salik %prec UMINUS
        { $$ = (void*)new_op("-", new_num(0), (Node*)$2); }
    ;

%%

/* ============================================================
 *  MAIN
 * ============================================================ */
int main() {
    /* tmpfile() fails on Windows when run without admin rights because it
     * tries to create files in C:\.  Use a named temp file in the proper
     * temp directory instead, then delete it on close. */
    char tmp_path[512];
#ifdef _WIN32
    char tmp_dir[256];
    DWORD tlen = GetTempPathA(sizeof(tmp_dir), tmp_dir);
    if (tlen == 0) strncpy(tmp_dir, ".", sizeof(tmp_dir));
    snprintf(tmp_path, sizeof(tmp_path), "%s\\wika_tmp_%lu.tmp",
             tmp_dir, (unsigned long)GetCurrentProcessId());
#else
    snprintf(tmp_path, sizeof(tmp_path), "/tmp/wika_tmp_%d.tmp", (int)getpid());
#endif
    FILE *code_buf = fopen(tmp_path, "w+b");
    if (!code_buf) {
        fprintf(stderr, "Hindi magawa ang pansamantalang buffer: %s\n", tmp_path);
        return 1;
    }

    fflush(stdout);
    int saved_fd = dup(STDOUT_FILENO);
    dup2(fileno(code_buf), STDOUT_FILENO);

    int parse_result = yyparse();

    fflush(stdout);
    dup2(saved_fd, STDOUT_FILENO);
    close(saved_fd);

    int total_errors = parse_error_count + sem_error_count;
    if (parse_result != 0 || total_errors > 0) {
        for (int i = 0; i < sem_error_count; i++)
            fprintf(stderr, "%s\n", sem_errors[i]);
        fprintf(stderr,
            "\nNatuklasan ang %d pagkakamali. Ihininto ang pagpapatakbo.\n",
            total_errors);
        fclose(code_buf);
        remove(tmp_path);
        return 1;
    }

    /* ── .data section ──
     *
     * bilang variables declared as .word64 (8 bytes).
     * titik  variables declared as .byte   (1 byte).
     */
    printf(".data\n");
    for (int i = 0; i < sym_count; i++) {
        if (sym[i].kind == KIND_TITIK) {
            printf("%s: .byte %ld\n", sym[i].name, sym[i].init_value);
        } else {
            printf("%s: .word64 %ld\n", sym[i].name, sym[i].init_value);
        }
    }
    printf("\n");

    /* ── .code section ── */
    printf(".code\nmain:\n");
    rewind(code_buf);
    int ch;
    while ((ch = fgetc(code_buf)) != EOF)
        putchar(ch);

    emit_syscall(0);

    fclose(code_buf);
    remove(tmp_path);
    return 0;
}

/* ============================================================
 *  yyerror — Syntax error handler (Tagalog messages)
 * ============================================================ */
void yyerror(const char *msg) {
    parse_error_count++;

    if (strstr(msg, "unexpected end of file") || strstr(msg, "unexpected $end")) {
        fprintf(stderr,
            "[Syntax Error sa Linya %d] Biglang katapusan ng file. "
            "Nakalimutan bang isulat ang 'tapos'?\n",
            yyline);
    } else if (strstr(msg, "unexpected IDENTIFIER")) {
        fprintf(stderr,
            "[Syntax Error sa Linya %d] Hindi inaasahang pangalan ng variable. "
            "Tiyaking naideklara at tama ang pagkakasunod-sunod.\n",
            yyline);
    } else if (strstr(msg, "unexpected NUMERO")) {
        fprintf(stderr,
            "[Syntax Error sa Linya %d] Hindi inaasahang numero. "
            "Tiyaking tama ang pagkakasulat ng ekspresyon.\n",
            yyline);
    } else if (strstr(msg, "unexpected BAGONG_LINYA")) {
        fprintf(stderr,
            "[Syntax Error sa Linya %d] Hindi kumpleto ang pahayag. "
            "Kumpletuhin ang deklarasyon, takda, o 'ipakita' bago lumipat sa bagong linya.\n",
            yyline);
    } else if (strstr(msg, "unexpected TAPOS")) {
        fprintf(stderr,
            "[Syntax Error sa Linya %d] Hindi inaasahang 'tapos'. "
            "May mali o kulang ba sa pahayag bago ang 'tapos'?\n",
            yyline);
    } else if (strstr(msg, "unexpected SIMULA")) {
        fprintf(stderr,
            "[Syntax Error sa Linya %d] Hindi inaasahang 'simula'. "
            "Isang 'simula' lang ang pinapayagan bawat programa.\n",
            yyline);
    } else {
        fprintf(stderr,
            "[Syntax Error sa Linya %d]: %s\n",
            yyline, msg);
    }
}
