%{
#include "wika.tab.h"
#include <string.h>
#include <stdlib.h>

int yyline = 1;
%}

%option noyywrap

%%

[ \t\r]+        { /* skip whitespace */ }
\n              { yyline++; return BAGONG_LINYA; }
"#"[^\n]*       { /* skip comments */ }

"simula"        { return SIMULA;     }
"tapos"         { return TAPOS;      }
"ipakita"       { return IPAKITA;    }
"bilang"        { return BILANG;     }
"titik"         { return TITIK;      }

"++"            { return DAGDAG_ISA; }
"--"            { return BAWAS_ISA;  }
"+="            { return DAGDAG_SET; }
"-="            { return BAWAS_SET;  }
"+"             { return PLUS;       }
"-"             { return MINUS;      }
"*"             { return BESES;      }
"/"             { return HATI;       }
"="             { return KATUMBAS;   }
"("             { return L_PAREN;    }
")"             { return R_PAREN;    }
","             { return KUWIT;      }

\'[^\']\' {
                    yylval.str = (char*)malloc(2);
                    yylval.str[0] = yytext[1];
                    yylval.str[1] = '\0';
                    return CHAR_LIT;
                }

[0-9]+[a-zA-Z_][a-zA-Z0-9_]* {
                    fprintf(stderr, "Linya %d: di-wastong token '%s' (numero at pangalan ay magkahiwalay)\n", yyline, yytext);
                }

[0-9]+          {
                    yylval.ival = atoi(yytext);
                    return NUMERO;
                }

[a-zA-Z_][a-zA-Z0-9_]*  {
                    yylval.str = strdup(yytext);
                    return IDENTIFIER;
                }

.               {
                    fprintf(stderr, "Linya %d: hindi kilalang karakter '%s'\n", yyline, yytext);
                }

%%
